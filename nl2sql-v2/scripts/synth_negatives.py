#!/usr/bin/env python3
"""Construct wrong answers for synthesized questions, instead of sampling them.

With DPO on (question, correct SQL, wrong SQL) triples, we never need the agent
to produce a *correct* candidate -- the gold already is one. We only need a wrong
one. And a wrong one does not have to be discovered by running episodes; it can
be written directly and verified by execution.

That removes the agent loop from the critical path. Measured, one agent episode
re-processes ~200,000 tokens of prefill (every step resends the whole
conversation), so K=3 over 1,000 questions is ~600M tokens through one GPU. A
constructed negative is one API call.

  sampling     1,000 questions x K=3  ->  3,000 episodes, ~13-250 GPU-hours,
                                          and only 90% yield a wrong answer
  construction 1,000 questions x N=2  ->  2,000 API calls, ~1 hour, ~$6,
                                          100% yield by construction

Each negative is checked against the gold with the SAME scorer semantics used to
grade the benchmark, so "wrong" means wrong the way our evaluation means it --
not merely textually different.

THE RISK, stated plainly: constructed negatives may be wrong in ways our
Qwen3.6-35B never is, so a model trained on them could learn to reject errors
that do not occur. Mitigated by templating each negative on the measured failure
taxonomy (the same taxonomy the question buckets come from), and checkable
against the real generator candidates in data/synth/babel30_candidates.jsonl.

Usage (from nl2sql-v2/):
    OPENAI_API_KEY=... uv run python scripts/synth_negatives.py \\
        --items ~/synth/main1k.jsonl --db-dir /path/to/filled \\
        --n-wrong 2 --base-url $OPENAI_BASE_URL --model gpt-5.4-mini \\
        --out ~/synth/main1k_negatives.jsonl --resume
"""

import argparse
import json
import os
import random
import sqlite3
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synth_questions import fences, key_spend, schema_text  # noqa: E402
from synth_solvecheck import scores  # noqa: E402



def stable_hash(s: str) -> int:
    """A process-independent digest.

    str.__hash__ is salted per interpreter (PYTHONHASHSEED), so seeding an RNG
    from hash() silently made --seed non-reproducible: the same seed produced
    different data on every run. Measured: hash("store_1.sqlite") & 0xFFFF gave
    14513, 33050 and 28089 across three processes.
    """
    return zlib.crc32(s.encode())

# One named error per negative, drawn from the measured failure taxonomy on the
# 135 local questions. Counts are lane-failures, so the mix reflects what our
# generator actually gets wrong rather than what is easy to break.
ERRORS = [
    ("wrong_values", 117,
     "Keep the row count and column count EXACTLY the same, but compute one "
     "figure wrongly: scope a denominator differently, include rows that should "
     "be excluded from an average, or aggregate at the wrong level. This is our "
     "most common real failure and the hardest to spot."),
    ("missing_filter", 26,
     "Drop or weaken one filter condition, so extra rows survive that should "
     "have been excluded."),
    ("set_vs_grain", 18,
     "Return one row per member of a set that was only meant to be a FILTER, "
     "instead of the single aggregate row the question asks for (or the "
     "reverse: collapse to one row when one row per entity was wanted)."),
    ("missing_column", 45,
     "Omit one column the question explicitly asks for. Keep everything else "
     "identical."),
    ("boundary", 13,
     "Get an edge wrong: use an inner join that silently drops entities with no "
     "matching rows, exclude a NULL-keyed group that belongs, or count rows "
     "where values should be counted."),
    ("fanout", 10,
     "Join a one-to-many relationship without aggregating first, so rows "
     "multiply."),
]

PROMPT = """You are writing a DELIBERATELY WRONG variant of a correct SQL query, to
train a model to tell correct answers from plausible-looking wrong ones.

Schema (SQLite):
{schema}

The question:
{question}

The CORRECT query, which returns {nrows} row(s) and {ncols} column(s):
```sql
{gold}
```

Write a variant that a competent analyst might plausibly have written but that is
WRONG, in this specific way:

{error}

Rules:
- It must RUN on SQLite as written and return at least 1 row.
- It must look like a serious attempt. No syntax errors, no obviously silly
  logic, no comments admitting it is wrong.
- Change as little as possible. The difference should be subtle enough that
  reading the SQL alone does not make it obvious.
- Keep the same column aliases where the error does not require changing them.
- Return ONLY the SQL in a ```sql fenced block. No commentary.
"""


def run(db, sql, cap=2000):
    cur = db.execute(sql)
    rows = cur.fetchmany(cap + 1)
    return rows[:cap], len(cur.description), len(rows) > cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--n-wrong", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--retries", type=int, default=3,
                    help="attempts per error type. Measured: 16 of 29 attempts "
                         "produced a variant that still scored CORRECT, so "
                         "retries are what take ready-rate from 80% to ~95%.")
    ap.add_argument("--workers", type=int, default=16,
                    help="items in flight. These are independent API calls; "
                         "serialising them is what made this a 6-hour job.")
    ap.add_argument("--max-spend", type=float, default=0.0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--watch", action="store_true",
                    help="poll --items for newly appended questions, so this "
                         "runs alongside synthesis instead of after it")
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--idle-exit", type=int, default=900)
    args = ap.parse_args()

    key = os.environ.get("OPENAI_API_KEY", "EMPTY")
    client = OpenAI(base_url=args.base_url, api_key=key)
    db_dir, items_p, out_p = Path(args.db_dir), Path(args.items), Path(args.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    done = set()
    if args.resume and out_p.exists():
        for line in out_p.open():
            try:
                done.add(json.loads(line)["item_id"])
            except Exception:
                pass
        print(f"resume: {len(done)} items already done")

    spend0 = key_spend(args.base_url, key)
    if spend0 is not None:
        print(f"key spend so far: ${spend0:.4f}"
              + (f" / cap ${args.max_spend:.2f}" if args.max_spend else ""))

    schema_cache: dict[str, str] = {}
    cache_lock, write_lock, tally_lock = (threading.Lock() for _ in range(3))
    tally = {"items": 0, "ready": 0, "negatives": 0, "rejected": 0}

    def schema_for(dbf: Path, db) -> str:
        with cache_lock:
            if dbf.name not in schema_cache:
                schema_cache[dbf.name] = schema_text(db)
            return schema_cache[dbf.name]

    def one_negative(schema, r, g_rows, g_ncols, desc, db):
        """Returns runnable SQL that our scorer grades WRONG, or None."""
        for _ in range(args.retries + 1):
            raw = client.chat.completions.create(
                model=args.model, temperature=args.temperature, max_tokens=1600,
                messages=[{"role": "user", "content": PROMPT.format(
                    schema=schema, question=r["question"], nrows=len(g_rows),
                    ncols=g_ncols, gold=r["gold_sql"], error=desc)}]
            ).choices[0].message.content or ""
            blocks = fences(raw)
            if not blocks:
                continue
            try:
                p_rows, p_ncols, p_tr = run(db, blocks[0])
            except Exception:
                continue
            if p_tr or not p_rows:
                continue
            # "Wrong" must mean wrong to OUR scorer, not merely different text.
            if scores(g_rows, g_ncols, p_rows, p_ncols):
                with tally_lock:
                    tally["rejected"] += 1
                continue
            return {"sql": blocks[0], "rows": len(p_rows), "cols": p_ncols}
        return None

    def work(r):
        dbf = db_dir / r["provenance"]["db_file"]
        if not dbf.exists():
            return None, f"  {r['id']}: {dbf.name} missing"
        db = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)  # per thread
        try:
            schema = schema_for(dbf, db)
            g_rows, g_ncols, trunc = run(db, r["gold_sql"])
            if trunc:
                return None, f"  {r['id']}: gold over cap"
            rng = random.Random(stable_hash(r["id"]) & 0xFFFF)
            # Error types weighted by how often each occurs in our measured
            # failures, so negatives mirror what the generator really gets wrong.
            picks = rng.sample([e for e in ERRORS for _ in range(max(1, e[1] // 13))],
                               k=min(args.n_wrong, len(ERRORS)))
            negs = []
            for name, _, desc in picks:
                got = one_negative(schema, r, g_rows, g_ncols, desc, db)
                if got:
                    negs.append({"error_type": name, **got})
            return {"item_id": r["id"], "bucket": r["bucket"],
                    "hard": r.get("hard", False), "db_file": dbf.name,
                    "question": r["question"], "gold_sql": r["gold_sql"],
                    "gold_rows": len(g_rows), "gold_cols": g_ncols,
                    "negatives": negs, "ready": bool(negs)}, None
        finally:
            db.close()

    idle = 0.0
    with out_p.open("a" if args.resume else "w") as f:
        while True:
            fresh = []
            if items_p.exists():
                for line in items_p.open():
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue            # a half-written final line
                    if r.get("status") == "pass" and r.get("gold_sql") \
                            and r["id"] not in done:
                        fresh.append(r)
            if not fresh:
                if not args.watch or idle >= args.idle_exit:
                    break
                time.sleep(args.poll); idle += args.poll
                continue
            idle = 0.0
            if args.max_spend:
                now = key_spend(args.base_url, key)
                if now is not None and now >= args.max_spend:
                    print(f"STOPPING: spend ${now:.4f} reached the cap"); break
            for r in fresh:
                done.add(r["id"])
            print(f"  {len(fresh)} items, {args.workers} workers")
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futs = {pool.submit(work, r): r for r in fresh}
                for fut in as_completed(futs):
                    try:
                        rec, msg = fut.result()
                    except Exception as e:
                        print(f"  {futs[fut]['id']}: {type(e).__name__}: {str(e)[:80]}")
                        continue
                    if msg:
                        print(msg); continue
                    with write_lock:
                        f.write(json.dumps(rec) + "\n"); f.flush()
                    with tally_lock:
                        tally["items"] += 1
                        tally["ready"] += rec["ready"]
                        tally["negatives"] += len(rec["negatives"])
                        n = tally["items"]; ready = tally["ready"]
                    print(f"  {rec['item_id']} [{rec['bucket']:19s}] "
                          f"{len(rec['negatives'])} wrong "
                          f"({','.join(x['error_type'] for x in rec['negatives']) or '-'})"
                          f" | ready {ready}/{n} = {ready/n:.0%}")

    n = max(tally["items"], 1)
    print(f"\n{tally['items']} items | ready {tally['ready']} ({tally['ready']/n:.0%}) "
          f"| {tally['negatives']} negatives | {tally['rejected']} rejected as "
          f"not-actually-wrong")
    s1 = key_spend(args.base_url, key)
    if spend0 is not None and s1 is not None:
        print(f"spend: ${s1-spend0:.4f} (${s1:.4f} cumulative) = "
              f"${(s1-spend0)/n:.4f}/item")


if __name__ == "__main__":
    main()
