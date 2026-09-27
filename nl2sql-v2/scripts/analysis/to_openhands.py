#!/usr/bin/env python3
"""Convert our episode traces into the OpenHands event format the
trajectory-visualizer renders (https://github.com/All-Hands-AI/trajectory-visualizer).

The visualizer accepts a bare JSON array of OpenHands events and dispatches on
(source, action|observation). Only the handlers wired into trajectory-list.tsx
render specially; anything else falls back to a raw-JSON card. So each of our
tools is mapped onto a handler that actually exists:

  run_sql_query          -> run_ipython   (args.code, renders as a code block)
  everything else        -> run           (args.command = "tool(arg=value)")
  any result starting    -> observation "error" instead of the paired one,
  with ERROR                so failures show up red rather than as normal output
  the question           -> user message
  assistant prose        -> assistant message
  reasoning, if present  -> assistant message prefixed "[reasoning]"
  final SQL + score      -> finish action

Two notes on that mapping. `think` actions are defined in the visualizer's types
and have a component, but trajectory-list.tsx never dispatches them, so real
reasoning would render as raw JSON -- hence folding it into assistant messages.
And our traces carry no timestamps, so monotonic synthetic ones are generated
(1 second apart) to keep the timeline ordering meaningful.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/to_openhands.py --runs q36_pass4_k4 --out ../logs/openhands
    uv run python scripts/analysis/to_openhands.py --runs 'q36_pass4_k*' --instances local031,local015
    uv run python scripts/analysis/to_openhands.py --runs q36_pass4_k4 --failures-only
"""

import argparse
import glob
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _common import TRACES_DIR

SQL_TOOLS = {"run_sql_query"}


def _clock():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    while True:
        yield t.isoformat().replace("+00:00", "Z")
        t += timedelta(seconds=1)


def _fmt_args(args) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return args
    if not isinstance(args, dict):
        return str(args)
    return ", ".join(f"{k}={json.dumps(v) if not isinstance(v, str) else v}"
                     for k, v in args.items())


def convert(trace: dict) -> list[dict]:
    clock = _clock()
    nid = iter(range(1, 100_000))
    ev: list[dict] = []
    ok = trace.get("score") == 1

    # The question goes first: App.tsx sniffs the format from element 0 and looks
    # for source+action there. Both of its branches behave the same, but starting
    # with the user message is also the OpenHands convention.
    ev.append({"id": next(nid), "timestamp": next(clock), "source": "user",
               "action": "message", "message": trace.get("question", ""),
               "args": {"content": trace.get("question", ""), "images_urls": []}})

    # The system prompt, as a collapsed card (source "system" collapses by default).
    if trace.get("system"):
        ev.append({"id": next(nid), "timestamp": next(clock), "source": "system",
                   "message": "System prompt",
                   "content": trace["system"], "system_prompt": trace["system"]})

    for e in trace.get("trace", []):
        if "tool" in e:
            tool, args = e["tool"], e.get("args")
            result = str(e.get("result") or "")
            failed = result.lstrip().upper().startswith("ERROR")
            aid = next(nid)
            if tool in SQL_TOOLS:
                sql = args.get("sql", "") if isinstance(args, dict) else str(args)
                ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                           "action": "run_ipython", "message": f"{tool}",
                           "args": {"code": sql, "is_confirmed": "confirmed",
                                    "kernel_init_code": "", "thought": ""}})
                obs = {"observation": "run_ipython", "extras": {"code": sql}}
            else:
                cmd = f"{tool}({_fmt_args(args)})"
                ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                           "action": "run", "message": tool,
                           "args": {"command": cmd, "is_confirmed": "confirmed",
                                    "thought": ""}})
                obs = {"observation": "run",
                       "extras": {"command": cmd, "command_id": aid,
                                  "exit_code": 1 if failed else 0, "metadata": {}}}
            if failed:
                obs = {"observation": "error", "extras": {}}
            ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
                       "cause": aid, "message": f"{tool} result",
                       "content": result, **obs})
            continue

        # An assistant turn: prose and/or reasoning. Tool calls in it are already
        # covered by the paired tool entries above, so only the text is emitted.
        msg = e.get("assistant")
        text = (msg.get("content") if isinstance(msg, dict) else msg) or ""
        for label, body in (("[reasoning]\n", e.get("reasoning")), ("", text)):
            if body and str(body).strip():
                content = f"{label}{body}"
                ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
                           "action": "message", "message": content,
                           "content": content,
                           "args": {"content": content, "images_urls": None,
                                    "wait_for_response": False}})

    ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
               "action": "finish",
               "message": f"{'CORRECT' if ok else 'FAILED'} — {trace.get('detail', '')}",
               "args": {"outputs": {"instance_id": trace.get("instance_id"),
                                    "score": trace.get("score"),
                                    "status": trace.get("status"),
                                    "detail": trace.get("detail"),
                                    "final_sql": trace.get("sql")},
                        "final_thought": (trace.get("sql") or "").strip(),
                        "task_completed": "true" if ok else "false"}})
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="q36_pass4_k4",
                    help="comma-separated run dir names or globs under logs/traces")
    ap.add_argument("--out", default=str(TRACES_DIR.parent / "openhands"))
    ap.add_argument("--instances", help="comma-separated ids; default all")
    ap.add_argument("--failures-only", action="store_true")
    args = ap.parse_args()

    keep = set(args.instances.split(",")) if args.instances else None
    out_root = Path(args.out)
    index, n = [], 0
    for spec in args.runs.split(","):
        for d in sorted(glob.glob(str(TRACES_DIR / spec))):
            d = Path(d)
            if not d.is_dir():
                continue
            for f in sorted(d.glob("local*.json")):
                t = json.loads(f.read_text())
                iid = t["instance_id"]
                if keep and iid not in keep:
                    continue
                if args.failures_only and t.get("score") == 1:
                    continue
                dest = out_root / d.name / f"{iid}.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(convert(t), indent=1))
                index.append({"run": d.name, "instance": iid,
                              "score": t.get("score"), "status": t.get("status"),
                              "detail": t.get("detail"),
                              "question": t.get("question", "")[:160],
                              "path": f"{d.name}/{iid}.json"})
                n += 1
    (out_root / "index.json").write_text(json.dumps(index, indent=1))
    print(f"wrote {n} trajectories to {out_root}")
    print(f"index: {out_root / 'index.json'}")


if __name__ == "__main__":
    main()
