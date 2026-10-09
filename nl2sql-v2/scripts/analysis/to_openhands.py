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
import csv
import glob
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import os
import sys

# nl2sql.config is stdlib-only (dataclasses/pathlib/os), so the paths and the source
# registry are available without pandas, duckdb or a Spider2 checkout. Everything
# needing those is imported lazily inside the gold layer, because the warehouse lanes
# convert with --gold-mode none and have to work on a machine where the Spider2
# submodule was never initialised.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from nl2sql.config import (DATA_SOURCES, GOLD_EXEC_DIR, GOLD_SQL_DIR,  # noqa: E402
                           REPO_ROOT, SQLITE_DIR)

TRACES_DIR = REPO_ROOT / "logs" / "traces"

SQL_TOOLS = {"run_sql_query"}
# write_file gets the diff viewer: on the dbt lane the model's whole deliverable is
# the model SQL it writes, and a `run` card would show it as one long command string.
EDIT_TOOLS = {"write_file"}
MAX_ROWS = 100          # rows shown per side of the diff


def _csv_text(df) -> str:
    body = df.head(MAX_ROWS).to_csv(index=False)
    if len(df) > MAX_ROWS:
        body += f"... {len(df) - MAX_ROWS} more rows\n"
    return body


def _gold_dir(source: str | None) -> Path:
    """Where this source's gold exec CSVs live (lite's own, unless overridden)."""
    src = DATA_SOURCES.get(source or "")
    return src.gold_exec_dir if src and src.gold_exec_dir else GOLD_EXEC_DIR


def gold_files_in(gold_dir: Path, iid: str) -> list[Path]:
    """Accepted gold CSVs for one instance: <iid>.csv plus <iid>_a/_b/... variants."""
    pat = re.compile(rf"^{re.escape(iid)}(_[a-z])?\.csv$")
    if not gold_dir.is_dir():
        return []
    return sorted(gold_dir / f for f in os.listdir(gold_dir) if pat.match(f))


def submitted_csv(trace: dict) -> str | None:
    """The CSV the graded query actually printed, recovered from the trace itself.

    The final SQL is echoed by exactly one run_sql_query call (verified: 194 of the
    194 bq_v2 episodes that submitted SQL), and that call's result is
    "query_id='qN'\n<csv>". So the submitted side of the diff costs no warehouse
    query -- the whole point on BigQuery, where re-executing 204 episodes would
    scan another terabyte.
    """
    sql = (trace.get("sql") or "").strip()
    if not sql:
        return None
    for e in trace.get("trace", []):
        if e.get("tool") not in SQL_TOOLS:
            continue
        if str((e.get("args") or {}).get("sql", "")).strip() != sql:
            continue
        body = str(e.get("result") or "")
        if body.startswith("query_id="):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        return body
    return None


def gold_comparison_csv(iid: str, trace: dict, gold_dir: Path) -> dict | None:
    """Gold CSV vs the submitted result, both read off disk. No database needed.

    Unlike gold_comparison() this does not re-score, so the card reports the score
    the run recorded rather than recomputing a verdict.
    """
    golds = gold_files_in(gold_dir, iid)
    if not golds:
        return None
    pred = submitted_csv(trace)
    gold = golds[0].read_text(encoding="utf-8", errors="replace")
    gold_rows = max(gold.count("\n") - 1, 0)
    note = [f"the run recorded {'CORRECT' if trace.get('score') == 1 else 'WRONG'}"
            f" ({trace.get('detail') or 'no detail'})",
            f"gold ~{gold_rows} rows ({golds[0].name})"]
    if len(golds) > 1:
        note.append(f"{len(golds)} accepted gold variants; showing {golds[0].name}")
    note.append("Left is gold, right is the preview the submitted query printed "
                "(capped by the tool, so a short right side is not a short answer). "
                "The scorer tolerates extra predicted columns, different column names "
                "and any row order, so textual differences do not by themselves mean "
                "the answer is wrong.")
    return {"path": f"{iid}: expected (left) vs submitted (right)",
            "old_content": gold,
            "new_content": pred if pred is not None else "<no SQL was submitted>",
            "content": "\n".join(note)}


def gold_comparison(iid: str, sql: str, db, std: dict,
                    gold_dir: Path | None = None) -> dict | None:
    """The graded gold table beside what the submitted query really returned.

    The scorer is looser than a text diff: it matches each gold column against
    some predicted column, tolerates EXTRA predicted columns, ignores row order
    on every local question, and allows 0.01 of numeric slack. So a query the
    scorer calls correct can still show textual differences here, and the card
    says so rather than letting the diff imply a verdict.
    """
    import pandas as pd

    from _common import score_against_gold

    golds = gold_files_in(gold_dir or GOLD_EXEC_DIR, iid)
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
            elif tool in EDIT_TOOLS:
                a = args if isinstance(args, dict) else {}
                path, body = str(a.get("path", "?")), str(a.get("content", ""))
                ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                           "action": "edit", "message": f"{tool} {path}",
                           "args": {"path": path, "old_content": "",
                                    "new_content": body,
                                    "thought": ""}})
                obs = {"observation": "edit",
                       "extras": {"path": path, "old_content": "",
                                  "new_content": body}}
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

        if "assistant" not in e:
            # Harness events: memory_compaction (171 of them in bq_v2 alone),
            # critic rounds, shape refusals. Dropping these hid the compaction
            # that rewrote the history under the model, which matters most on
            # exactly the long episodes worth reading.
            kind = next((k for k in e if k not in ("step", "reasoning")), "event")
            payload = e.get(kind)
            body = (payload if isinstance(payload, str)
                    else json.dumps(payload, indent=1, default=str))
            aid = next(nid)
            cmd = f"{kind}()"
            ev.append({"id": aid, "timestamp": next(clock), "source": "agent",
                       "action": "run", "message": kind,
                       "args": {"command": cmd, "is_confirmed": "confirmed",
                                "thought": ""}})
            ev.append({"id": next(nid), "timestamp": next(clock), "source": "agent",
                       "cause": aid, "observation": "run", "message": kind,
                       "content": body,
                       "extras": {"command": cmd, "command_id": aid,
                                  "exit_code": 0, "metadata": {}}})
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


def questions_for(source: str) -> dict:
    """instance_id -> question record for one DATA_SOURCES entry, or {} if its
    jsonl is absent (a fresh clone without the Spider2 submodule). The converter
    only needs this for the re-execution gold mode; everything shown in the viewer
    comes from the trace itself."""
    src = DATA_SOURCES.get(source)
    if src is None:
        raise SystemExit(f"unknown --source {source!r}; "
                         f"choose from {', '.join(sorted(DATA_SOURCES))}")
    if not src.questions_file.exists():
        return {}
    out = {}
    with open(src.questions_file, encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            iid = q["instance_id"]
            if src.id_prefix and not iid.startswith(src.id_prefix):
                continue
            if src.id_prefixes and not iid.startswith(src.id_prefixes):
                continue
            if any(iid.startswith(x) for x in src.id_exclude_prefixes):
                continue
            for canon, src_key in src.field_map.items():
                if canon not in q and src_key in q:
                    q[canon] = q[src_key]
            out[iid] = q
    return out


def load_run_csv(paths: str | None) -> dict:
    """instance_id -> row, merged over one or more run CSVs.

    The run CSV is the authority on the score: trace files carry the score the
    harness wrote at episode end, but the dbt lane is scored afterwards by
    score_dbt.py, so its traces say nothing useful.
    """
    rows = {}
    for spec in (paths or "").split(","):
        spec = spec.strip()
        if not spec:
            continue
        for path in sorted(glob.glob(spec)) or [spec]:
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rows[r["instance_id"]] = r
    return rows


def resolve_gold_mode(mode: str, source: str, gold_dir: Path) -> str:
    """auto -> the richest mode this machine can actually serve."""
    if mode != "auto":
        return mode
    if not gold_dir.is_dir():
        return "none"
    src = DATA_SOURCES.get(source)
    sqlite_lane = src is not None and src.dialect == "duckdb_sqlite"
    if sqlite_lane and SQLITE_DIR.is_dir():
        return "exec"          # re-execute: the graded table, not the preview
    return "csv"               # read both sides off disk; no database needed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="q36_pass4_k4",
                    help="comma-separated run dir names or globs under logs/traces")
    ap.add_argument("--source", default="spider2",
                    help="DATA_SOURCES key the runs came from (spider2, "
                         "spider2_lite_bq, spider2_dbt, ...); sets the gold paths "
                         "and the question field names")
    ap.add_argument("--out", default=str(TRACES_DIR.parent / "openhands"))
    ap.add_argument("--instances", help="comma-separated ids; default all")
    ap.add_argument("--run-csv",
                    help="run CSV(s) or glob; authoritative for score/status and "
                         "the source of the steps and scan_bytes columns")
    ap.add_argument("--failures-only", action="store_true")
    ap.add_argument("--gold-mode", default="auto",
                    choices=["auto", "none", "csv", "exec"],
                    help="auto: exec on the SQLite lane, csv where gold CSVs exist, "
                         "else none. csv reads gold and the submitted preview off "
                         "disk (no queries). exec re-runs the submitted SQL through "
                         "DuckDB (SQLite lane only).")
    ap.add_argument("--no-gold", action="store_true",
                    help="alias for --gold-mode none")
    args = ap.parse_args()

    keep = set(args.instances.split(",")) if args.instances else None
    out_root = Path(args.out)
    gold_dir = _gold_dir(args.source)
    mode = "none" if args.no_gold else resolve_gold_mode(
        args.gold_mode, args.source, gold_dir)
    runs_csv = load_run_csv(args.run_csv)

    jobs = []           # (run_dir_name, trace)
    for spec in args.runs.split(","):
        for d in sorted(glob.glob(str(TRACES_DIR / spec))):
            d = Path(d)
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.json")):
                t = json.loads(f.read_text(encoding="utf-8"))
                iid = t.get("instance_id") or f.stem
                t["instance_id"] = iid
                if keep and iid not in keep:
                    continue
                row = runs_csv.get(iid)
                if row:     # the run CSV wins; see load_run_csv
                    t["score"] = 1 if row.get("score") == "1" else 0
                    t["status"] = row.get("status") or t.get("status")
                    t["detail"] = row.get("score_detail") or t.get("detail")
                    t["_steps"] = row.get("steps")
                    t["_scan_bytes"] = row.get("scan_bytes")
                if args.failures_only and t.get("score") == 1:
                    continue
                jobs.append((d.name, t))
    if not jobs:
        raise SystemExit(f"no traces matched --runs {args.runs}")

    comparisons = {}
    if mode == "csv":
        for run, t in jobs:
            cmp = gold_comparison_csv(t["instance_id"], t, gold_dir)
            if cmp:
                comparisons[(run, t["instance_id"])] = cmp
        print(f"gold mode 'csv': {len(comparisons)}/{len(jobs)} episodes have a "
              f"gold CSV in {gold_dir}")
    elif mode == "exec":
        from _common import Database, load_eval_standards

        Q = questions_for(args.source)
        if not Q:
            raise SystemExit(f"--gold-mode exec needs the questions file for "
                             f"{args.source}, which is missing (Spider2 submodule "
                             f"not initialised?). Use --gold-mode csv or none.")
        std = load_eval_standards()
        # Group by database so each SQLite file is attached once, not once per episode.
        by_db = defaultdict(list)
        for run, t in jobs:
            q = Q.get(t["instance_id"])
            if q:
                by_db[q["db"]].append((run, t))
        print(f"executing {sum(len(v) for v in by_db.values())} submitted queries "
              f"across {len(by_db)} databases for the gold diff ...")
        for db_name, items in sorted(by_db.items()):
            path = SQLITE_DIR / f"{db_name}.sqlite"
            db = Database(path) if path.exists() else None
            for run, t in items:
                comparisons[(run, t["instance_id"])] = gold_comparison(
                    t["instance_id"], t.get("sql") or "", db, std, gold_dir)
            if db is not None:
                db.close()
    else:
        print("gold mode 'none': no expected-vs-submitted diff")

    index, n = [], 0
    for run, t in jobs:
        iid = t["instance_id"]
        gold_sql_file = GOLD_SQL_DIR / f"{iid}.sql"
        has_gold_sql = gold_sql_file.exists()
        dest = out_root / run / f"{iid}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(convert(
            t, comparisons.get((run, iid)),
            gold_sql_file.read_text(encoding="utf-8") if has_gold_sql else ""),
            indent=1), encoding="utf-8")
        sc = [str(e.get("result") or "") for e in t.get("trace", [])
              if e.get("tool") == "search_context"]
        sc_err = sum(1 for r in sc if r.lstrip().upper().startswith("ERROR"))
        index.append({"run": run, "instance": iid,
                      # Surfaced in the index because two runs of the same model can
                      # differ only by whether retrieval worked, and the episodes
                      # otherwise look alike. "n/a" means the lane had no retrieval
                      # at all, which is not the same as retrieval being broken.
                      "search": ("n/a" if not sc else
                                 "BROKEN" if sc_err == len(sc) else
                                 f"{len(sc) - sc_err}/{len(sc)} ok"),
                      "score": t.get("score"), "status": t.get("status"),
                      "detail": t.get("detail"),
                      "steps": t.get("_steps"),
                      "scan_bytes": t.get("_scan_bytes"),
                      "tool_calls": sum(1 for e in t.get("trace", []) if "tool" in e),
                      "has_gold_diff": comparisons.get((run, iid)) is not None,
                      "has_gold_sql": has_gold_sql,
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

    # Merge with whatever is already on disk, keeping rows from runs this call did
    # not touch, so each lane can be converted with its own --source/--run-csv.
    converted = {r["run"] for r in index}
    try:
        previous = json.loads((out_root / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = []
    kept = [r for r in previous if r.get("run") not in converted]
    index = kept + index

    mtime = {}
    for run in {r["run"] for r in index}:
        files = list((TRACES_DIR / run).glob("*.json"))
        mtime[run] = max((f.stat().st_mtime for f in files), default=0)
    fam_mtime = {}
    for run, t in mtime.items():
        fam_mtime[family(run)] = max(fam_mtime.get(family(run), 0), t)
    newest = max(fam_mtime.values(), default=0)
    for r in index:
        r["recency"] = ("current" if fam_mtime[family(r["run"])] == newest
                        else "superseded")
    index.sort(key=lambda r: (-fam_mtime[family(r["run"])], r["run"], r["instance"]))
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "index.json").write_text(json.dumps(index, indent=1),
                                         encoding="utf-8")
    with_diff = sum(1 for r in index if r.get("has_gold_diff"))
    scored = sum(1 for r in index if r.get("score") == 1 and r["run"] in converted)
    print(f"wrote {n} trajectories to {out_root}")
    print(f"  correct in this conversion: {scored}/{n}")
    if kept:
        print(f"  kept {len(kept)} rows from {len(set(r['run'] for r in kept))} "
              f"other run(s) already in the index")
    print(f"  with an expected-vs-submitted diff: {with_diff}")
    print(f"  with the official gold SQL too    : "
          f"{sum(1 for r in index if r.get('has_gold_sql'))}")
    print(f"index: {out_root / 'index.json'}")


if __name__ == "__main__":
    main()
