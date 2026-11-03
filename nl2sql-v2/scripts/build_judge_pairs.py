#!/usr/bin/env python3
"""Assemble judge-training pairs from synthesized questions + verified negatives.

The committed dataset is not trainable as it stands. `main1k_negatives.jsonl`
records each negative's row and column COUNT but not its values, and 59% of the
negatives return exactly gold's (rows, cols) -- so the counts are precisely the
signal that does not discriminate. This re-executes both queries to get the
actual result, which is the evidence the judge is asked to rule on.

The unit judged is the executed RESULT, not the query: `validator_select.py`
already says "Judge the result, not the style". Three measurements say the
training input should match that framing rather than hand the model SQL plus an
instruction not to look at it -- "pick the longer SQL" scores 61.3% on these
pairs, our golds come from gpt-5.4-mini while real candidates come from Qwen in
a tool loop, and showing the judge more of how an answer was produced made it
monotonically worse (51 -> 48 across five reasoning modes).

So SQL and schema are separate ablation axes, not a bundle:

    arm A   question + schema + two results          deployment-faithful
    arm B   question + schema + two results + SQL    more evidence, shortcut-prone
    arm C   question + two SQLs, NO results          the control

Arm C is the diagnostic. If it lands near B, then B's edge is SQL style rather
than judgement, and since our SQL distribution differs from real candidates that
edge is fictional.

Records are side-agnostic -- `chosen`/`rejected` name the ANSWER, not a position
-- and the renderer emits each pair twice with the sides swapped, so the model
never sees a label attached to a position. That is the structural fix for the
measured 44% order-flip rate.

Usage (from nl2sql-v2/, on a machine that can see the databases):
    uv run python scripts/build_judge_pairs.py \\
        --items ../data/synth/main1k.jsonl \\
        --negatives ../data/synth/main1k_negatives.jsonl \\
        --db-dir ~/synsql_filled --out-dir ../data/judge
"""

import argparse
import collections
import csv
import io
import json
import random
import re
import sqlite3
import sys
import time
import zlib
from pathlib import Path

PREVIEW_ROWS = 15

# Table references come from FROM/JOIN, not a substring scan: a CTE named
# song_feature_counts is not a table, and a bare \btable\b search over the whole
# query picks up aliases and CTE names as if they were.
_FROM_JOIN = re.compile(r"\b(?:FROM|JOIN)\s+[\"'\[`]?([A-Za-z_][A-Za-z0-9_]*)", re.I)


def stable_hash(s: str) -> int:
    """Process-independent digest; str.__hash__ is salted per interpreter."""
    return zlib.crc32(s.encode())


def arm_timeout(db, seconds):
    """Bound every query on this connection.

    Gold and negative queries run window functions over joined fact tables, and
    one pathological plan would otherwise block the whole assembly with no way
    to tell progress from a hang. SQLite's progress handler is the only
    interrupt that works from the calling thread.
    """
    deadline = [float("inf")]

    def handler():
        return 1 if time.monotonic() > deadline[0] else 0

    db.set_progress_handler(handler, 20000)

    def arm():
        deadline[0] = time.monotonic() + seconds

    return arm


def tables_of(db, sqls) -> list[str]:
    real = {t[0].lower(): t[0] for t in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    hit, seen = [], set()
    for sql in sqls:
        for name in _FROM_JOIN.findall(sql):
            k = name.lower()
            if k in real and k not in seen:
                seen.add(k)
                hit.append(real[k])
    return hit


def compact_schema(db, tables) -> str:
    """One line per table: name(col, col, ...). Full DDL with per-column comments
    is 56.6% of a full-evidence prompt; the column vocabulary is the part the
    judge needs, because our scorer fails a missing column and ignores extras."""
    out = []
    for t in tables:
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        out.append(f"{t}({', '.join(cols)})")
    return "\n".join(out)


def result_csv(db, sql, cap=PREVIEW_ROWS):
    cur = db.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(cap + 1)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows[:cap]:
        w.writerow(["" if v is None else v for v in r])
    s = buf.getvalue().rstrip("\n")
    if len(rows) > cap:
        s += f"\n... (more than {cap} rows)"
    return s


# ---------------------------------------------------------------- rendering

HEAD = ("You are picking which candidate answer correctly answers a question "
        "about a SQL database.\n\nQUESTION\n{q}\n")
SCHEMA = "\nDATABASE SCHEMA\n{schema}\n"
TAIL = ("\nWhich candidate correctly answers the question? "
        "Reply with a single letter.\nANSWER:")

ARMS = ("A", "B", "C")


def render(arm, rec, first):
    """`first` is which side ("chosen"/"rejected") is shown as candidate A."""
    second = "rejected" if first == "chosen" else "chosen"
    sides = [("A", rec[first]), ("B", rec[second])]
    p = [HEAD.format(q=rec["question"])]
    if arm in ("A", "B"):
        p.append(SCHEMA.format(schema=rec["schema"]))
    if arm == "C":
        p.append("\nTwo candidate queries were written. Exactly one is correct.\n")
    else:
        p.append("\nTwo candidate answers were produced independently. "
                 "Each is the result of a query.\n")
    for letter, side in sides:
        if arm == "A":
            p.append(f"\nANSWER {letter}  ({side['rows']} rows x {side['cols']} columns)\n"
                     f"{side['result_csv']}\n")
        elif arm == "B":
            p.append(f"\nCANDIDATE {letter}\nSQL:\n{side['sql']}\n"
                     f"RESULT ({side['rows']} rows x {side['cols']} columns)\n"
                     f"{side['result_csv']}\n")
        else:
            p.append(f"\nCANDIDATE {letter}\n{side['sql']}\n")
    p.append(TAIL)
    return "".join(p), ("A" if first == "chosen" else "B")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--negatives", required=True)
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--holdout", type=float, default=0.15,
                    help="fraction of QUESTIONS (never pairs) held out")
    ap.add_argument("--missing-column-cap", type=int, default=100,
                    help="missing_column is 99.7%% 'pick the longer SQL' and 98%% "
                         "shape-detectable, so it is mostly a shortcut. It cannot "
                         "be length-balanced internally -- almost every one has "
                         "gold longer -- so it is capped instead, and the "
                         "resulting baseline is reported.")
    ap.add_argument("--tokenizer", default="Qwen/Qwen3.6-35B-A3B",
                    help="for REAL sequence lengths; chars/3.6 is calibrated on "
                         "prose and badly under-counts a numeric prompt")
    ap.add_argument("--query-timeout", type=float, default=120.0,
                    help="seconds per pair of query executions; a pair that "
                         "exceeds it is skipped and counted, not left to hang")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_dir = Path(args.db_dir).expanduser()
    rng = random.Random(args.seed)

    neg_recs = [json.loads(l) for l in open(args.negatives)]
    ready = [r for r in neg_recs if r.get("ready")]
    print(f"{len(neg_recs)} negative records, {len(ready)} with >=1 verified wrong answer")

    # ---- composition: cap missing_column, keep everything else
    flat = []
    for r in ready:
        for i, n in enumerate(r["negatives"]):
            flat.append((r, i, n))
    mc = [x for x in flat if x[2]["error_type"] == "missing_column"]
    rest = [x for x in flat if x[2]["error_type"] != "missing_column"]
    rng.shuffle(mc)
    kept = rest + mc[:args.missing_column_cap]
    print(f"composition: {len(rest)} non-missing_column + "
          f"{min(len(mc), args.missing_column_cap)} of {len(mc)} missing_column "
          f"= {len(kept)} pairs")

    # ---- question-level split, stratified by (bucket, hard)
    qs = sorted({r["item_id"] for r, _, _ in kept})
    strat = collections.defaultdict(list)
    meta = {r["item_id"]: (r["bucket"], bool(r.get("hard"))) for r, _, _ in kept}
    for q in qs:
        strat[meta[q]].append(q)
    held = set()
    for key, group in sorted(strat.items()):
        group = sorted(group, key=lambda q: stable_hash(f"{args.seed}|{q}"))
        k = max(1, round(len(group) * args.holdout)) if len(group) > 1 else 0
        held.update(group[:k])
    print(f"split: {len(qs)} questions -> {len(qs)-len(held)} train / {len(held)} held out "
          f"({len(held)/len(qs):.0%}), stratified over {len(strat)} (bucket,hard) cells")

    # ---- assemble: re-execute both queries
    pairs, skipped = [], collections.Counter()
    dbcache = {}
    pairs_path = out_dir / "pairs.jsonl"
    pf = pairs_path.open("w")
    t0 = time.monotonic()
    for k, (r, i, n) in enumerate(kept, 1):
        if k % 50 == 0 or k == len(kept):
            el = time.monotonic() - t0
            print(f"  {k}/{len(kept)} pairs | {len(pairs)} ok | "
                  f"{len(dbcache)} dbs | {el:.0f}s "
                  f"({el/max(k,1):.2f}s/pair, eta {(len(kept)-k)*el/max(k,1):.0f}s)",
                  flush=True)
        dbf = db_dir / r["db_file"]
        if not dbf.exists():
            skipped["db missing"] += 1
            continue
        hit = dbcache.get(dbf.name)
        if hit is None:
            db = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
            hit = dbcache[dbf.name] = (db, arm_timeout(db, args.query_timeout))
        db, arm = hit
        try:
            arm()
            tabs = tables_of(db, [r["gold_sql"], n["sql"]])
            if not tabs:
                skipped["no tables parsed"] += 1
                continue
            rec = {
                "pair_id": f"{r['item_id']}#{i}",
                "item_id": r["item_id"],
                "question": r["question"],
                "schema": compact_schema(db, tabs),
                "tables": tabs,
                "chosen": {"sql": r["gold_sql"].strip(), "rows": r["gold_rows"],
                           "cols": r["gold_cols"],
                           "result_csv": result_csv(db, r["gold_sql"])},
                "rejected": {"sql": n["sql"].strip(), "rows": n["rows"],
                             "cols": n["cols"], "error_type": n["error_type"],
                             "result_csv": result_csv(db, n["sql"])},
                "bucket": r["bucket"],
                "hard": bool(r.get("hard")),
                "db_file": r["db_file"],
                "split": "holdout" if r["item_id"] in held else "train",
            }
        except Exception as e:
            skipped[f"{type(e).__name__}"] += 1
            continue
        pairs.append(rec)
        pf.write(json.dumps(rec) + "\n")
        pf.flush()
    pf.close()
    for db, _ in dbcache.values():
        db.close()
    print(f"assembled {len(pairs)} pairs"
          + (f" | skipped {dict(skipped)}" if skipped else ""))

    # ---- render each arm, position-balanced
    tok = None
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(args.tokenizer)
        print(f"tokenizer: {args.tokenizer}")
    except Exception as e:
        print(f"tokenizer unavailable ({type(e).__name__}); "
              f"reporting chars only -- do NOT trust chars/3.6 on numeric prompts")

    print()
    for arm in ARMS:
        counts = collections.Counter()
        lens = []
        path = out_dir / f"arm{arm}.jsonl"
        with path.open("w") as f:
            for p in pairs:
                for first in ("chosen", "rejected"):
                    prompt, target = render(arm, p, first)
                    f.write(json.dumps({
                        "pair_id": p["pair_id"], "item_id": p["item_id"],
                        "split": p["split"], "arm": arm,
                        "prompt": prompt, "target": target,
                        "error_type": p["rejected"]["error_type"],
                        "bucket": p["bucket"], "hard": p["hard"],
                        "gold_rows": p["chosen"]["rows"],
                    }) + "\n")
                    counts[p["split"]] += 1
                    lens.append(len(tok(prompt)["input_ids"]) if tok else len(prompt))
        lens.sort()
        unit = "tokens" if tok else "chars"
        print(f"arm{arm}.jsonl: {sum(counts.values())} examples "
              f"({counts['train']} train / {counts['holdout']} holdout) | "
              f"{unit} p50={lens[len(lens)//2]} p90={lens[int(.9*len(lens))]} "
              f"max={lens[-1]}")

    # ---- baselines the curve needs as reference lines
    print()
    longer = sum(len(p["chosen"]["sql"]) > len(p["rejected"]["sql"]) for p in pairs)
    eq = sum(len(p["chosen"]["sql"]) == len(p["rejected"]["sql"]) for p in pairs)
    print("reference baselines on the assembled set:")
    print(f"  'pick the longer SQL'   {100*(longer+0.5*eq)/len(pairs):.1f}%  "
          f"(was 61.3% before capping missing_column)")
    same = sum(p["chosen"]["rows"] == p["rejected"]["rows"]
               and p["chosen"]["cols"] == p["rejected"]["cols"] for p in pairs)
    print(f"  shape collides with gold  {100*same/len(pairs):.0f}%  "
          f"-- these are undecidable from (rows, cols) alone")
    print(f"  'always A'               50.0%  (exact, by position balance)")
    ho = [p for p in pairs if p["split"] == "holdout"]
    print(f"\nheld-out: {len(ho)} pairs over "
          f"{len({p['item_id'] for p in ho})} questions | "
          f"1-row golds {100*sum(p['chosen']['rows']==1 for p in ho)/max(len(ho),1):.0f}% "
          f"(the decidability-risk slice)")
    print(f"\nwrote {out_dir}/pairs.jsonl + armA/armB/armC.jsonl")


if __name__ == "__main__":
    main()
