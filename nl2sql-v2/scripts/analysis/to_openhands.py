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
  gold vs submitted      -> edit observation, which renders a real diff viewer
  official gold SQL      -> read observation (only 24 locals ship one)
  final SQL + score      -> finish action

Two notes on that mapping. `think` actions are defined in the visualizer's types
and have a component, but trajectory-list.tsx never dispatches them, so real
reasoning would render as raw JSON -- hence folding it into assistant messages.
And our traces carry no timestamps, so monotonic synthetic ones are generated
(1 second apart) to keep the timeline ordering meaningful.

The gold comparison re-executes each submitted query through the agent's own DuckDB
path, so the "submitted" side is the table that was actually graded rather than the
truncated preview the tool printed. Pass --no-gold to skip that and convert faster.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/to_openhands.py --runs q36_pass4_k4 --out ../logs/openhands
    uv run python scripts/analysis/to_openhands.py --runs 'q36_pass4_k*' --instances local031,local015
    uv run python scripts/analysis/to_openhands.py --runs q36_pass4_k4 --failures-only
"""

import argparse
import glob
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from _common import (GOLD_SQL_DIR, SQLITE_DIR, TRACES_DIR, Database, gold_files,
                     load_eval_standards, local_questions, score_against_gold)

SQL_TOOLS = {"run_sql_query"}
MAX_ROWS = 100          # rows shown per side of the diff


def _csv_text(df: pd.DataFrame) -> str:
    body = df.head(MAX_ROWS).to_csv(index=False)
    if len(df) > MAX_ROWS:
        body += f"... {len(df) - MAX_ROWS} more rows\n"
    return body


def gold_comparison(iid: str, sql: str, db: "Database | None", std: dict) -> dict | None:
    """The graded gold table beside what the submitted query really returned.

    The scorer is looser than a text diff: it matches each gold column against
    some predicted column, tolerates EXTRA predicted columns, ignores row order
    on every local question, and allows 0.01 of numeric slack. So a query the
    scorer calls correct can still show textual differences here, and the card
    says so rather than letting the diff imply a verdict.
    """
    golds = gold_files(iid)
    if not golds:
        return None
    try:
        if db is None:
            raise RuntimeError("database file is missing")
        pred, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
    except Exception as exc:
        pred, verdict = None, f"the submitted query does not execute: {exc}"
    if pred is not None:
        ok, detail = score_against_gold(pred, iid, std)
        verdict = f"scorer says {'CORRECT' if ok == 1 else 'WRONG'} ({detail})"

    # With several accepted variants, diff against the one closest in shape.
    frames = []
    for f in golds:
        try:
            frames.append((f.name, pd.read_csv(f)))
        except Exception:
            pass
    if not frames:
        return None
    if pred is not None and len(frames) > 1:
        frames.sort(key=lambda nf: (abs(nf[1].shape[1] - pred.shape[1]),
                                    abs(nf[1].shape[0] - pred.shape[0])))
    name, gold = frames[0]
    note = [verdict,
            f"gold {gold.shape[0]} rows x {gold.shape[1]} cols ({name})"]
    if len(frames) > 1:
        note.append(f"{len(frames)} accepted gold variants; showing the closest in shape")
    if pred is not None:
        note.append(f"submitted {pred.shape[0]} rows x {pred.shape[1]} cols")
    note.append("The scorer tolerates extra predicted columns, different column "
                "names and any row order, so textual differences below do not by "
                "themselves mean the answer is wrong.")
    return {"path": f"{iid}: expected (left) vs submitted (right)",
            "old_content": _csv_text(gold),
            "new_content": _csv_text(pred) if pred is not None else "<did not execute>",
            "content": "\n".join(note)}


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


def convert(trace: dict, cmp: dict | None = None, gold_sql: str = "") -> list[dict]:
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

    # The graded comparison, as an edit observation: the viewer renders those with a
    # real side-by-side diff viewer, which is exactly the shape of this question.
    if cmp:
        aid = next(nid)
        ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                   "action": "edit", "message": "expected vs submitted output",
                   "args": {"path": cmp["path"], "old_content": cmp["old_content"],
                            "new_content": cmp["new_content"],
                            "thought": "compare the submitted result with the gold answer"}})
        ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
                   "cause": aid, "observation": "edit",
                   "message": "expected vs submitted output",
                   "content": cmp["content"],
                   "extras": {"path": cmp["path"], "old_content": cmp["old_content"],
                              "new_content": cmp["new_content"]}})

    if gold_sql:
        aid = next(nid)
        ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                   "action": "read", "message": "official gold SQL",
                   "args": {"path": "gold.sql"}})
        ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
                   "cause": aid, "observation": "read", "message": "official gold SQL",
                   "content": gold_sql, "extras": {"path": "gold.sql"}})

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
    ap.add_argument("--no-gold", action="store_true",
                    help="skip the expected-vs-submitted diff (no query execution)")
    args = ap.parse_args()

    keep = set(args.instances.split(",")) if args.instances else None
    out_root = Path(args.out)
    Q = local_questions()

    jobs = []           # (run_dir_name, trace)
    for spec in args.runs.split(","):
        for d in sorted(glob.glob(str(TRACES_DIR / spec))):
            d = Path(d)
            if not d.is_dir():
                continue
            for f in sorted(d.glob("local*.json")):
                t = json.loads(f.read_text())
                if keep and t["instance_id"] not in keep:
                    continue
                if args.failures_only and t.get("score") == 1:
                    continue
                jobs.append((d.name, t))
    if not jobs:
        raise SystemExit(f"no traces matched --runs {args.runs}")

    # Group by database so each SQLite file is attached once, not once per episode.
    comparisons = {}
    if not args.no_gold:
        std = load_eval_standards()
        by_db = defaultdict(list)
        for run, t in jobs:
            by_db[Q[t["instance_id"]]["db"]].append((run, t))
        print(f"executing {len(jobs)} submitted queries across {len(by_db)} databases "
              f"for the gold diff ...")
        for db_name, items in sorted(by_db.items()):
            path = SQLITE_DIR / f"{db_name}.sqlite"
            db = Database(path) if path.exists() else None
            for run, t in items:
                comparisons[(run, t["instance_id"])] = gold_comparison(
                    t["instance_id"], t.get("sql") or "", db, std)
            if db is not None:
                db.close()

    index, n = [], 0
    for run, t in jobs:
        iid = t["instance_id"]
        gold_sql_file = GOLD_SQL_DIR / f"{iid}.sql"
        dest = out_root / run / f"{iid}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(convert(
            t, comparisons.get((run, iid)),
            gold_sql_file.read_text() if gold_sql_file.exists() else ""), indent=1))
        sc = [str(e.get("result") or "") for e in t.get("trace", [])
              if e.get("tool") == "search_context"]
        sc_err = sum(1 for r in sc if r.lstrip().upper().startswith("ERROR"))
        index.append({"run": run, "instance": iid,
                      # Surfaced in the index because two runs of the same model differ
                      # only by whether retrieval worked, and the episodes look alike.
                      "search": ("unused" if not sc else
                                 "BROKEN" if sc_err == len(sc) else
                                 f"{len(sc) - sc_err}/{len(sc)} ok"),
                      "score": t.get("score"), "status": t.get("status"),
                      "detail": t.get("detail"),
                      "has_gold_diff": comparisons.get((run, iid)) is not None,
                      "has_gold_sql": gold_sql_file.exists(),
                      "question": t.get("question", "")[:160],
                      "path": f"{run}/{iid}.json"})
        n += 1
    # Order runs newest first, by the most recent trace in each source directory, so
    # a superseded run never sits above the current one. Two runs of the same model
    # can differ only in whether retrieval worked and are otherwise indistinguishable.
    # Group lanes and shards into one run family first ("q36s_pass4_k3" and
    # "q36s_pass4_k4" are one run), otherwise only the single newest lane counts
    # as current and its siblings look superseded.
    def family(run: str) -> str:
        return re.sub(r"_(k\d+|r\d+)?_?\d*$", "", run) or run

    mtime = {}
    for run in {r["run"] for r in index}:
        files = list((TRACES_DIR / run).glob("local*.json"))
        mtime[run] = max((f.stat().st_mtime for f in files), default=0)
    fam_mtime = {}
    for run, t in mtime.items():
        fam_mtime[family(run)] = max(fam_mtime.get(family(run), 0), t)
    newest = max(fam_mtime.values(), default=0)
    for r in index:
        r["recency"] = ("current" if fam_mtime[family(r["run"])] == newest
                        else "superseded")
    index.sort(key=lambda r: (-fam_mtime[family(r["run"])], r["run"], r["instance"]))
    (out_root / "index.json").write_text(json.dumps(index, indent=1))
    with_diff = sum(1 for r in index if r["has_gold_diff"])
    print(f"wrote {n} trajectories to {out_root}")
    print(f"  with an expected-vs-submitted diff: {with_diff}")
    print(f"  with the official gold SQL too    : {sum(1 for r in index if r['has_gold_sql'])}")
    print(f"index: {out_root / 'index.json'}")


if __name__ == "__main__":
    main()
