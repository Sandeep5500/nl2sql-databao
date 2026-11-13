#!/usr/bin/env python3
"""Result comparisons for the diff_cmp judge variant (judge_prompts.py): for every ordered pair of
groups in the chosen selection-eval pools, the two groups' full results compared by
result_compare.py, written as <out> lines {key, first, second, text}; rejudge_pools.py
--comparisons reads them.

Full results:
- Spider2: each group's SQL is re-run once as judge_pools.py ran it (Database.query_preview(sql,
  1, 5000, timeout 60 s), then canonical), and kept only if it reproduces the stored group: same
  shape and every stored preview row present (the stored preview came from the group's first
  lane, whose row order can differ from the representative SQL's).
- BigQuery: the stored trace output of the group's first lane (<= 50 rows plus the true row
  count), never re-run (BigQuery bills per byte).
A pair with an unavailable side gets "Comparison unavailable."; the summary counts them.

Usage (on Babel, NL2SQL_DATA_ROOT set; from nl2sql-v2/):
    python scripts/build_compare_cache.py --evalset selection_evalset.json --pools $W/results/pools \\
        --bq-pools $B/pools --bq-base $B/bigquery_passk_nov2026 --select "half=design|test|bq" \\
        --out compare_cache.jsonl [--shard k/n] [--sqlite-dir DIR]
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from result_compare import compare_results

UNAVAILABLE = "Comparison unavailable."


def preview_rows(preview):
    """(data rows as CSV lines, header line) of a stored preview."""
    lines = preview.rstrip("\n").split("\n")
    body = lines[:-1] if lines and lines[-1].startswith("[") else lines
    return body[1:], body[0] if body else ""


def reproduces(df, g, rows=None):
    """df is the stored group's result: same shape and every stored preview row present."""
    rows = df.shape[0] if rows is None else rows
    if rows != g["rows"] or df.shape[1] != g["cols"]:
        return False
    text = df.to_csv(index=False).rstrip("\n").split("\n")
    shown, header = preview_rows(g["preview"])
    if text and header and text[0] != header:
        return False
    have = set(text[1:])
    return all(r in have for r in shown)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evalset", required=True)
    ap.add_argument("--select", default="")
    ap.add_argument("--pools", required=True)
    ap.add_argument("--ref-prefix", default="think35/qwen36-35b-think")
    ap.add_argument("--bq-pools", default="")
    ap.add_argument("--bq-ref-prefix", default="think35_bq")
    ap.add_argument("--bq-base")
    ap.add_argument("--sqlite-dir", help="override nl2sql.config.SQLITE_DIR (local tests)")
    ap.add_argument("--shard", help="k/n: every n-th pool starting at k")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from rejudge_pools import load_reference
    ev = json.loads(Path(args.evalset).read_text())["pools"]
    filt = [f.split("=") for f in args.select.split(";") if f]
    keys = sorted(k for k, e in ev.items() if e["stratum"] in ("contested", "easy")
                  and all(str(e[name]) in want.split("|") for name, want in filt))
    if args.shard:
        k0, n = map(int, args.shard.split("/"))
        keys = keys[k0::n]
    ref = load_reference(args.pools, args.ref_prefix, args.bq_pools, args.bq_ref_prefix)

    full = {}  # (key, group) -> (df, true rows, capped) or None
    sp = [k for k in keys if k.startswith("spider2:")]
    bq = [k for k in keys if k.startswith("bq:")]
    if sp:
        from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
        from nl2sql.db import Database
        from select_answer import canonical
        sqlite_dir = Path(args.sqlite_dir) if args.sqlite_dir else SQLITE_DIR
        qdb = {q["instance_id"]: q["db"] for q in map(json.loads, open(QUESTIONS_FILE))}
        dbs, by_sql = {}, {}
        for k in sp:
            it, e = ref[k], ev[k]
            db = qdb[it["instance_id"]]
            if db not in dbs:
                dbs[db] = Database(sqlite_dir / f"{db}.sqlite")
            for a, g in enumerate(it["groups"]):
                if e["groups"][a][0] == 0:
                    continue
                sk = (db, g["sql"])
                if sk not in by_sql:
                    try:
                        df, _ = dbs[db].query_preview(g["sql"], 1, 5000, timeout_s=60)
                        by_sql[sk] = canonical(df)
                    except Exception as ex:
                        print(f"{k} group {a}: {str(ex)[:100]}", flush=True)
                        by_sql[sk] = None
                df = by_sql[sk]
                full[(k, a)] = (df, df.shape[0], False) if df is not None and reproduces(df, g) else None
        for d in dbs.values():
            d.close()
    if bq:
        from bq_judge_pools import LANES, final_result, parse_result
        base = Path(args.bq_base)
        lane_sql = {}
        for k in bq:
            it, e = ref[k], ev[k]
            iid = it["instance_id"]
            for a, g in enumerate(it["groups"]):
                if e["groups"][a][0] == 0:
                    continue
                full[(k, a)] = None
                for lane in sorted(g["lanes"]):  # the first lane built the stored preview
                    if lane not in lane_sql:
                        lane_sql[lane] = {r["instance_id"]: r for r in csv.DictReader(open(base / LANES[lane] / "all.csv"))}
                    sql = (lane_sql[lane][iid].get("sql") or "").replace("\\n", "\n").strip()
                    tr = json.load(open(base / LANES[lane] / "traces" / f"{iid}.json"))
                    res = final_result(tr, sql)
                    if res is None:
                        continue
                    try:
                        df, total, capped = parse_result(res)
                    except Exception:
                        continue
                    if reproduces(df.head(8), {**g, "rows": total, "preview": g["preview"]}, rows=total) or \
                            (df.head(8).to_csv(index=False) + f"[{total} rows x {df.shape[1]} cols total]") == g["preview"]:
                        full[(k, a)] = (df, total, total > df.shape[0])
                        break

    n_pairs = n_unavail = 0
    with open(args.out, "w") as out:
        for k in keys:
            alive = [a for a, g in enumerate(ev[k]["groups"]) if g[0] > 0]
            for a in alive:
                for b in alive:
                    if a == b:
                        continue
                    fa, fb = full.get((k, a)), full.get((k, b))
                    if fa is None or fb is None:
                        text = UNAVAILABLE
                        n_unavail += 1
                    else:
                        text = compare_results(fa[0], fb[0], fa[1], fb[1], capped=fa[2] or fb[2])
                    n_pairs += 1
                    out.write(json.dumps({"key": k, "first": a, "second": b, "text": text}) + "\n")
    groups = [v for v in full.values()]
    print(f"{len(keys)} pools, {len(groups)} groups ({sum(g is None for g in groups)} unavailable), "
          f"{n_pairs} ordered pairs ({n_unavail} unavailable) -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
