#!/usr/bin/env python3
"""Run our agent harness on SYNTHESIZED questions to produce labelled candidates.

This is the consumer half of the pipeline. run_benchmark.py is built around
Spider 2.0 instances -- it loads from QUESTIONS_FILE, resolves DCE datasources
and scores against gold exec CSVs -- none of which applies to questions we wrote
ourselves over foreign databases. So this drives run_episode directly.

Why it matters that the generator here is OUR model: the judge has to
discriminate the specific ways Qwen3.6-35B goes wrong inside our tool loop, and
no public dataset carries that error distribution. The questions are foreign; the
mistakes must be ours.

--watch makes it a pipeline consumer: it re-reads the items file and picks up
newly appended ones, so candidate generation (GPU-bound) overlaps synthesis
(API-bound) instead of waiting for it. The point is less the ~2.5h saved than
getting a mixed-rate measurement after ~100 items rather than after all 3,000.

Usage (from nl2sql-v2/):
    uv run python scripts/synth_candidates.py \\
        --items ../data/synth/run1.jsonl --db-dir /path/to/filled \\
        --k 6 --temperature 0.7 --endpoint http://babel-x-y:8765/v1 \\
        --out ../data/synth/run1_candidates.jsonl --watch --shard 0/4
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI

from nl2sql.agent import run_episode
from nl2sql.config import AgentConfig, LLMConfig
from nl2sql.db import Database
from nl2sql.tools import ToolSession
from run_benchmark import read_endpoint
from synth_solvecheck import scores


def gold_of(db_path: Path, sql: str, cap: int = 2000):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(sql)
        rows = cur.fetchmany(cap + 1)
        return rows[:cap], len(cur.description), len(rows) > cap
    finally:
        con.close()


def load_items(path: Path, shard=None):
    out = []
    if not path.exists():
        return out
    for line in path.open():
        try:
            r = json.loads(line)
        except Exception:
            continue                      # a partially written final line
        if r.get("status") == "pass" and r.get("gold_sql"):
            out.append(r)
    if shard:
        i, n = shard
        out = [r for k, r in enumerate(out) if k % n == i]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--endpoint")
    ap.add_argument("--model")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--shard", help="I/N, round-robin, so lanes run in parallel")
    ap.add_argument("--watch", action="store_true",
                    help="keep polling --items for newly appended questions")
    ap.add_argument("--poll", type=int, default=30, help="seconds between polls")
    ap.add_argument("--idle-exit", type=int, default=900,
                    help="give up after this many seconds with nothing new")
    args = ap.parse_args()

    base_url = read_endpoint(args.endpoint)
    client = OpenAI(base_url=base_url, api_key="EMPTY")
    model = args.model or client.models.list().data[0].id
    llm = LLMConfig(base_url=base_url, model=model, temperature=args.temperature,
                    chat_template_kwargs={"enable_thinking": False}
                    if "qwen" in model.lower() else {})
    cfg = AgentConfig(max_steps=args.max_steps)
    shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None

    items_path, out_path = Path(args.items), Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in out_path.open():
            try:
                done.add(json.loads(line)["item_id"])
            except Exception:
                pass
        print(f"resume: {len(done)} items already in {out_path.name}")

    db_dir = Path(args.db_dir)
    tally = {"items": 0, "mixed": 0, "all_right": 0, "all_wrong": 0, "pairs": 0}
    idle = 0.0
    with out_path.open("a") as f:
        while True:
            fresh = [r for r in load_items(items_path, shard) if r["id"] not in done]
            if not fresh:
                if not args.watch:
                    break
                if idle >= args.idle_exit:
                    print(f"\nnothing new for {idle:.0f}s; exiting")
                    break
                time.sleep(args.poll)
                idle += args.poll
                continue
            idle = 0.0
            for r in fresh:
                done.add(r["id"])
                dbf = db_dir / (r["provenance"]["db_file"] if "provenance" in r
                                else r.get("db", ""))
                if not dbf.exists():
                    print(f"  {r['id']}: database {dbf.name} not found, skipped")
                    continue
                try:
                    g_rows, g_ncols, trunc = gold_of(dbf, r["gold_sql"])
                except Exception as e:
                    print(f"  {r['id']}: gold re-execute failed: {e}")
                    continue
                if trunc:
                    print(f"  {r['id']}: gold over cap, skipped")
                    continue

                cands = []
                for lane in range(args.k):
                    db = Database(dbf)
                    try:
                        session = ToolSession(db=db, cfg=cfg)
                        res = run_episode(r["question"], session, llm, cfg)
                        sql = res.sql or ""
                        ok = False
                        if sql:
                            try:
                                p_rows, p_ncols, p_tr = gold_of(dbf, sql)
                                ok = (not p_tr) and scores(g_rows, g_ncols, p_rows, p_ncols)
                            except Exception:
                                ok = False
                        cands.append({"lane": lane, "sql": sql, "correct": ok,
                                      "steps": len(res.trace), "status": res.status,
                                      "error": res.error})
                    except Exception as e:
                        cands.append({"lane": lane, "sql": "", "correct": False,
                                      "error": f"{type(e).__name__}: {str(e)[:120]}"})
                    finally:
                        db.close()

                nc = sum(c["correct"] for c in cands)
                rec = {"item_id": r["id"], "bucket": r["bucket"],
                       "db_file": dbf.name, "question": r["question"],
                       "gold_sql": r["gold_sql"],
                       "gold_rows": len(g_rows), "gold_cols": g_ncols,
                       "n_correct": nc, "k": len(cands), "candidates": cands}
                f.write(json.dumps(rec) + "\n"); f.flush()
                tally["items"] += 1
                if nc == 0:
                    tally["all_wrong"] += 1
                elif nc == len(cands):
                    tally["all_right"] += 1
                else:
                    tally["mixed"] += 1
                    tally["pairs"] += nc * (len(cands) - nc)
                n = tally["items"]
                print(f"  {r['id']} [{r['bucket']:19s}] {nc}/{len(cands)} correct | "
                      f"running: mixed {tally['mixed']}/{n} = {tally['mixed']/n:.0%}, "
                      f"{tally['pairs']} pairs")

    n = max(tally["items"], 1)
    print(f"\n{tally['items']} items | mixed {tally['mixed']} ({tally['mixed']/n:.0%}) "
          f"| all-right {tally['all_right']} | all-wrong {tally['all_wrong']}")
    print(f"raw pairs: {tally['pairs']}  ({tally['pairs']/n:.2f} per question)")
    print("\nmixed rate is the plan's softest number -- 51% assumed from Spider 2.0, "
          "which swings training pairs by ~2,000.")


if __name__ == "__main__":
    main()
