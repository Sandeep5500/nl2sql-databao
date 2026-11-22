#!/usr/bin/env python3
"""Render the real pass@4 candidates as arm-B pairwise prompts.

The judge adapters were trained on a single-token pairwise task: question +
compact schema + two (SQL, result) candidates + "ANSWER:" -> "A"/"B". The
deployed validator instead shows all four candidates and asks for free text.
Feeding the 4-way prompt to the adapter would be out of distribution, so each
question is decomposed into its 6 pairs, each rendered in both orders (12
renderings), scored, and aggregated back into a single pick.

Nothing derived from the gold answer enters a prompt. `correct` travels
alongside for scoring only, exactly as validator_inputs.json already does.

Usage (from nl2sql-v2/):
    python scripts/build_pass4_pairs.py \
        --inputs validator_inputs_rg.json \
        --db-dir ../Spider2/spider2-lite/resource/databases/spider2-localdb \
        --out ../results/pass4_armB.jsonl
"""

import argparse
import itertools
import json
import re
import sqlite3
from pathlib import Path

# same templates as build_judge_pairs.py -- train/serve consistency is the
# entire point of this script, so these must not drift
HEAD = ("You are picking which candidate answer correctly answers a question "
        "about a SQL database.\n\nQUESTION\n{q}\n")
SCHEMA = "\nDATABASE SCHEMA\n{schema}\n"
TAIL = ("\nWhich candidate correctly answers the question? "
        "Reply with a single letter.\nANSWER:")

_FROM_JOIN = re.compile(r"\b(?:FROM|JOIN)\s+[\"'\[`]?([A-Za-z_][A-Za-z0-9_]*)", re.I)
PREVIEW_ROWS = 20


def tables_in(sqls, known):
    """Tables named by any candidate, intersected with what the DB really has."""
    want, low = set(), {t.lower(): t for t in known}
    for s in sqls:
        for m in _FROM_JOIN.findall(s or ""):
            t = low.get(m.lower())
            if t:
                want.add(t)
    return sorted(want)


def compact_schema(db, tables):
    out = []
    for t in tables:
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        out.append(f"{t}({', '.join(cols)})")
    return "\n".join(out)


def trim_preview(preview, cap=PREVIEW_ROWS):
    """Cap the stored preview to the row budget the training prompts used."""
    lines = (preview or "").splitlines()
    return "\n".join(lines[: cap + 1])  # +1 for the header row


def render(question, schema, a, b):
    """arm B: compact schema + both candidates' SQL and results."""
    p = [HEAD.format(q=question)]
    if schema:
        p.append(SCHEMA.format(schema=schema))
    p.append("\nTwo candidate answers were produced independently. "
             "Each is the result of a query.\n")
    for letter, side in (("A", a), ("B", b)):
        rows, cols = side["shape"] if side.get("shape") else ("?", "?")
        p.append(f"\nCANDIDATE {letter}\nSQL:\n{side['sql']}\n"
                 f"RESULT ({rows} rows x {cols} columns)\n"
                 f"{trim_preview(side.get('preview'))}\n")
    p.append(TAIL)
    return "".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-schema", action="store_true",
                    help="omit the schema block (for a matched ablation)")
    args = ap.parse_args()

    data = json.load(open(args.inputs))
    db_dir = Path(args.db_dir)
    out = open(args.out, "w")

    n_rend = n_q = n_dec = 0
    missing_db = set()
    for iid, rec in sorted(data.items()):
        cands = rec["candidates"]
        if len(cands) < 2:
            continue
        schema = ""
        if not args.no_schema:
            p = db_dir / f"{rec['db']}.sqlite"
            if p.exists():
                db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                known = [r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]
                schema = compact_schema(db, tables_in([c["sql"] for c in cands], known))
                db.close()
            else:
                missing_db.add(rec["db"])
        n_q += 1
        for i, j in itertools.combinations(range(len(cands)), 2):
            ci, cj = cands[i], cands[j]
            # decisive = exactly one correct; only these have a right answer
            decisive = ci["correct"] != cj["correct"]
            if decisive:
                n_dec += 1
            for first in (i, j):
                a, b = (ci, cj) if first == i else (cj, ci)
                target = None
                if decisive:
                    target = "A" if a["correct"] else "B"
                out.write(json.dumps({
                    "instance_id": iid, "db": rec["db"],
                    "i": i, "j": j, "first": first,
                    "prompt": render(rec["question"], schema, a, b),
                    "target": target, "decisive": decisive,
                    "i_correct": ci["correct"], "j_correct": cj["correct"],
                    "i_label": ci["label"], "j_label": cj["label"],
                }) + "\n")
                n_rend += 1
    out.close()
    print(f"{n_q} questions -> {n_rend} renderings "
          f"({n_rend // 2} pairs, {n_dec} decisive) -> {args.out}")
    if missing_db:
        print(f"WARNING no sqlite for: {sorted(missing_db)}")


if __name__ == "__main__":
    main()
