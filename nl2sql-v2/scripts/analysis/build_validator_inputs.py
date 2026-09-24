#!/usr/bin/env python3
"""Freeze the pass@4 candidates into one file a validator model can be run on.

For each question: the question text, its documentation if any, and the four
candidate answers (SQL + result shape + a preview of the rows). Candidate order
is shuffled deterministically per question so a model cannot learn "lane 1 is
usually best", and so position bias does not favour one run.

Writes validator_inputs.json. Executing the stored SQL here, once, means every
validator model sees byte-identical prompts.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/build_validator_inputs.py
    uv run python scripts/analysis/build_validator_inputs.py --runs 'v2_armAplus,v2_pass4_k*'
"""

import argparse
import json
import random
from pathlib import Path

import json as _json

from _common import (LANES, SQLITE_DIR, Database, load_traces, local_questions,
                     rescore)
from nl2sql.config import DOCS_DIR

OUT = Path(__file__).resolve().parents[2] / "validator_inputs.json"
LETTERS = "ABCDEFGH"


def reasoning_of(trace: dict) -> dict:
    """What the agent said while producing this candidate. Its own summary comes
    from the submit_result call (absent when it ran out of steps); the narration
    is its visible message at each step. Recorded verbatim: it can be confidently
    wrong, which is part of what a validator has to see through."""
    summary, msgs, thinking = None, [], []
    for e in trace.get("trace", []):
        if (e.get("reasoning") or "").strip():
            thinking.append(e["reasoning"].strip())
        a = e.get("assistant") or {}
        if (a.get("content") or "").strip():
            msgs.append(a["content"].strip())
        for tc in a.get("tool_calls", []):
            if tc["function"]["name"] == "submit_result":
                try:
                    summary = _json.loads(tc["function"]["arguments"]).get("result_description")
                except Exception:
                    pass
    return {"summary": summary, "last_messages": msgs[-2:], "narration": "\n".join(msgs),
            "thinking": "\n---\n".join(thinking), "thinking_last": "\n---\n".join(thinking[-2:])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=",".join(LANES))
    ap.add_argument("--preview-rows", type=int, default=15)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    Q = local_questions()
    qdb = {k: v["db"] for k, v in Q.items()}
    specs = args.runs.split(",")
    traces = load_traces(specs)
    ok = rescore(traces, qdb)      # recorded for scoring later, never shown to the model

    out = {}
    for db_name in sorted({qdb[i] for i in Q}):
        path = SQLITE_DIR / f"{db_name}.sqlite"
        if not path.exists():
            continue
        db = Database(path)
        for iid in sorted(i for i in Q if qdb[i] == db_name):
            cands = []
            for spec in specs:
                t = traces[spec].get(iid)
                if not t or not t.get("sql"):
                    continue
                sql = t["sql"]
                try:
                    df, csv = db.query_preview(sql, args.preview_rows, 5000)
                    shape, preview, err = list(df.shape), csv, None
                except Exception as e:
                    shape, preview, err = None, None, f"{type(e).__name__}: {str(e)[:150]}"
                cands.append({"run": spec, "sql": sql, "shape": shape,
                              "preview": preview, "error": err,
                              "status": t.get("status"),
                              "reasoning": reasoning_of(t),
                              "correct": bool(ok.get((spec, iid)))})
            if len(cands) < 2:
                continue
            random.Random(iid).shuffle(cands)      # deterministic, kills position bias
            for k, c in enumerate(cands):
                c["label"] = LETTERS[k]
            doc = None
            if Q[iid].get("external_knowledge"):
                p = DOCS_DIR / Q[iid]["external_knowledge"]
                doc = p.read_text()[:6000] if p.exists() else None
            out[iid] = {"db": db_name, "question": Q[iid]["question"],
                        "doc": doc, "candidates": cands}
        db.close()
        print(".", end="", flush=True)
    print()

    Path(args.out).write_text(json.dumps(out, indent=1))
    n = len(out)
    mixed = sum(1 for v in out.values()
                if 0 < sum(c["correct"] for c in v["candidates"]) < len(v["candidates"]))
    print(f"wrote {args.out}: {n} questions, {sum(len(v['candidates']) for v in out.values())} candidates")
    print(f"  decidable (some right, some wrong): {mixed}")
    print(f"  all candidates wrong: {sum(1 for v in out.values() if not any(c['correct'] for c in v['candidates']))}")
    print(f"  all candidates right: {sum(1 for v in out.values() if all(c['correct'] for c in v['candidates']))}")
    print(f"  with documentation attached: {sum(1 for v in out.values() if v['doc'])}")


if __name__ == "__main__":
    main()
