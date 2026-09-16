#!/usr/bin/env python3
"""Convert a v2 trace directory (+ results CSV) into an Inspect AI .eval log
so traces can be browsed with `inspect view`.

Usage (from nl2sql-v2/):
    uv run python scripts/traces_to_inspect.py ../logs/traces/v2_smoke5 \
        --csv ../results/v2_smoke5.csv
    uv run inspect view --log-dir ../logs/inspect
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.log import (EvalConfig, EvalDataset, EvalLog, EvalSample,
                            EvalSpec, write_eval_log)
from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser)
from inspect_ai.scorer import Score
from inspect_ai.tool import ToolCall

INSPECT_LOG_DIR = Path(__file__).resolve().parents[2] / "logs/inspect"


def trace_to_messages(t: dict) -> list:
    msgs = [ChatMessageSystem(content=t.get("system") or
                              "(system prompt not stored in this trace)"),
            ChatMessageUser(content=f"Question: {t['question']}")]
    pending_tool_ids: list[tuple[str, str]] = []  # (call_id, fn name) awaiting results

    for e in t.get("trace", []):
        if "assistant" in e:
            a = e["assistant"]
            calls = []
            pending_tool_ids = []
            for tc in a.get("tool_calls", []):
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {"raw": tc["function"]["arguments"]}
                calls.append(ToolCall(id=tc["id"], function=tc["function"]["name"],
                                      arguments=args))
                pending_tool_ids.append((tc["id"], tc["function"]["name"]))
            msgs.append(ChatMessageAssistant(content=a.get("content") or "",
                                             tool_calls=calls or None))
        elif "tool" in e:
            call_id, fn = pending_tool_ids.pop(0) if pending_tool_ids else (None, e["tool"])
            msgs.append(ChatMessageTool(content=str(e.get("result", "")),
                                        tool_call_id=call_id, function=fn))
        elif "critic" in e:
            v = e["critic"]
            msgs.append(ChatMessageUser(
                content=f"[CRITIC GATE] approve={v.get('approve')} "
                        f"feedback: {v.get('feedback', '')}"))
        elif "memory_compaction" in e:
            m = e["memory_compaction"]
            body = m.get("summary") or m.get("error", "")
            msgs.append(ChatMessageUser(
                content=f"[MEMORY COMPACTION] folded {m.get('folded_msgs', '?')} "
                        f"messages into:\n{body}"))
    return msgs


def convert(trace_dir: Path, csv_path: Path | None = None,
            model: str = "unknown", out_dir: Path = INSPECT_LOG_DIR) -> Path:
    rows = {}
    if csv_path and Path(csv_path).exists():
        rows = {r["instance_id"]: r for r in csv.DictReader(open(csv_path))}

    samples = []
    for f in sorted(Path(trace_dir).glob("*.json")):
        t = json.loads(f.read_text())
        iid = t["instance_id"]
        r = rows.get(iid, {})
        score_val = t.get("score", r.get("score", 0))
        samples.append(EvalSample(
            id=iid, epoch=1,
            input=t["question"],
            target="(gold exec_result CSV)",
            messages=trace_to_messages(t),
            scores={"exec_match": Score(
                value=int(score_val or 0),
                answer=t.get("sql") or "",
                explanation=f"{t.get('detail', r.get('score_detail', ''))} | "
                            f"status={t.get('status', r.get('status', ''))} | "
                            f"steps={r.get('steps', '?')}")},
            metadata={k: r[k] for k in ("db", "steps", "critic_rounds",
                                        "search_calls", "wall_seconds") if k in r},
        ))

    run_name = Path(trace_dir).name
    log = EvalLog(
        version=2, status="success",
        eval=EvalSpec(
            created=datetime.now(timezone.utc).isoformat(),
            task=f"spider2-lite-local/{run_name}",
            dataset=EvalDataset(name="spider2-lite-local", samples=len(samples)),
            model=model,
            config=EvalConfig(),
        ),
        samples=samples,
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{run_name}.eval"
    write_eval_log(log, str(out))
    print(f"wrote {len(samples)} samples -> {out}")
    print(f"view with:  uv run inspect view --log-dir {out_dir}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_dir", type=Path)
    ap.add_argument("--csv", type=Path, help="results CSV (adds scores/status)")
    ap.add_argument("--model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--out-dir", type=Path, default=INSPECT_LOG_DIR)
    args = ap.parse_args()
    convert(args.trace_dir, args.csv, args.model, args.out_dir)


if __name__ == "__main__":
    main()
