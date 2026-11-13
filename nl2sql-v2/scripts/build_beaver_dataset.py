#!/usr/bin/env python3
"""Build a judge-training question set from BEAVER (enterprise warehouse questions over three
MySQL databases: dw, nova, neutron) in the layout nl2sql/config.py reads under
NL2SQL_DATASET_DIR, as build_bird_dataset.py does for BIRD-Platinum.

The gold results are BEAVER's gold SQL run on MySQL (beaver_gold_mysql.py), the dialect it was
written for. The agent runs DuckDB over the SQLite copies (beaver_to_sqlite.py), so each gold is
also translated to DuckDB (sqlglot) and run there:
  agrees      the scorer accepts the DuckDB result against MySQL's (kept)
  disagrees   it rejects it: MySQL's case-insensitive collation, a conversion difference, or a
              translation error decided the answer (dropped)
  unverified  the translation fails or times out (kept, marked; MySQL's result stands)
Also dropped: questions close to one of the 135 Spider2 local questions, gold with no rows or
more than --max-rows rows, gold whose LIMIT cuts through tied rows (probed on DuckDB), and gold
using VARIANCE/STDDEV/STD: MySQL's are the population measures and DuckDB's (what sqlglot maps
them to, and what an agent writing DuckDB gets) the sample ones, so the question's wording
("use STDDEV, never STDDEV_POP") leads a DuckDB agent away from the gold. They were 58% of the
golds with 1-50 rows and most of the engine disagreements.

Split by database: --heldout-dbs are never trained on.

Usage (from nl2sql-v2/):
    uv run python scripts/build_beaver_dataset.py --questions ~/beaver-staging/beaver-query/data \\
        --gold-dir /data/user_data/$USER/beaver/mysql_gold --dbs /data/user_data/$USER/beaver/databases \\
        --out /data/user_data/$USER/judge-data/beaver
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_bird_dataset import near_spider2, spider2_questions, ties_at_limit
from nl2sql.db import Database
from nl2sql.eval import _csv_roundtrip, compare_dataframes

PREFIX = "beaver_"
VARIANCE = re.compile(r"\b(VARIANCE|VAR_POP|VAR_SAMP|STDDEV|STDDEV_POP|STDDEV_SAMP|STD)\s*\(", re.I)


def to_duckdb(sql: str) -> str | None:
    try:
        import sqlglot
        return sqlglot.transpile(sql, read="mysql", write="duckdb")[0]
    except Exception:
        return None


def engine_check(db_path: Path, duck_sql: str | None, gold_df, timeout_s: float) -> str:
    if duck_sql is None:
        return "unverified"
    gold = _csv_roundtrip(gold_df.copy())
    db = Database(db_path)
    try:
        try:
            duck, _ = db.query_preview(duck_sql, 1, 100_000, timeout_s=timeout_s)
        except Exception:
            return "unverified"
        return "agrees" if compare_dataframes(_csv_roundtrip(duck), gold, ignore_order=True) else "disagrees"
    finally:
        db.close()


def tie_at_limit(db_path: Path, duck_sql: str | None, timeout_s: float) -> bool:
    if duck_sql is None:
        return False
    db = Database(db_path)
    try:
        def run(s, n):
            df, _ = db.query_preview(s, 1, n, timeout_s=timeout_s)
            return [tuple(r) for r in df.itertuples(index=False)]
        return ties_at_limit(duck_sql, run, dialect="duckdb")
    finally:
        db.close()


def knowledge(raw) -> str:
    try:
        items = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError):
        items = [raw]
    lines = [str(x).strip() for x in items if str(x).strip()]
    return "\n".join(f"- {x}" for x in lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="BEAVER's beaver-query parquet directory")
    ap.add_argument("--gold-dir", required=True, help="beaver_gold_mysql.py output")
    ap.add_argument("--dbs", required=True, help="dir with <db>.sqlite (beaver_to_sqlite.py)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--heldout-dbs", default="neutron")
    ap.add_argument("--max-rows", type=int, default=50)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    out, gold_dir = Path(args.out), Path(args.gold_dir)
    held = set(filter(None, args.heldout_dbs.split(",")))

    qs = pd.concat([pd.read_parquet(Path(args.questions) / f) for f in sorted(os.listdir(args.questions))
                    if f.endswith(".parquet")]).to_dict("records")
    runs = {r["id"]: r for r in map(json.loads, open(gold_dir / "results.jsonl"))}
    print(f"{len(qs)} BEAVER questions")

    dropped, keep = Counter(), []
    s2 = spider2_questions()
    for x in qs:
        r = runs.get(x["id"])
        if r is None or r["status"] != "ok":
            dropped["gold_failed_on_mysql"] += 1
        elif r["rows"] == 0:
            dropped["gold_empty"] += 1
        elif r["rows"] > args.max_rows:
            dropped["gold_too_many_rows"] += 1
        elif VARIANCE.search(x["sql"]):
            dropped["gold_variance_or_stddev"] += 1
        elif near_spider2(x["question"], s2):
            dropped["near_spider2_question"] += 1
        else:
            keep.append(x)
    print(f"{len(keep)} with 1-{args.max_rows} gold rows")

    for d in ("documents", "gold/exec_result", "gold/sql"):  # written only here: a rebuild starts clean
        shutil.rmtree(out / d, ignore_errors=True)
    for d in ("databases", "documents", "gold/exec_result", "gold/sql", "dce/src/databases"):
        (out / d).mkdir(parents=True, exist_ok=True)
    dbs = sorted({x["db"] for x in keep})
    for db in dbs:
        link = out / "databases" / f"{db}.sqlite"
        if not link.exists():
            link.symlink_to((Path(args.dbs) / f"{db}.sqlite").resolve())
        (out / "dce/src/databases" / f"{db}.yaml").write_text(
            f"type: sqlite\nname: {db}\nconnection:\n  database_path: {link.absolute()}\n")
    if not (out / "dce/dce.ini").exists():
        (out / "dce/dce.ini").write_text(f"[DEFAULT]\nproject-id = {uuid.uuid4()}\n")
    split = {"heldout": sorted(held & set(dbs)), "train": sorted(set(dbs) - held), "denied": {}}
    (out / "db_split.json").write_text(json.dumps(split, indent=1) + "\n")

    def check(x):
        path = out / "databases" / f"{x['db']}.sqlite"
        df = pd.read_csv(gold_dir / "exec_result" / f"{x['id']}.csv")
        duck = to_duckdb(x["sql"])
        if tie_at_limit(path, duck, args.timeout):
            return df, "gold_tie_at_limit"
        return df, engine_check(path, duck, df, args.timeout)

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(check, keep))
    print(f"checked in {time.time() - t0:.0f}s: {dict(Counter(e for _, e in results))}")

    questions, standards = [], []
    for x, (df, verdict) in zip(keep, results):
        if verdict in ("disagrees", "gold_tie_at_limit"):
            dropped["engine_disagrees" if verdict == "disagrees" else verdict] += 1
            continue
        iid = PREFIX + x["id"]
        df.to_csv(out / "gold/exec_result" / f"{iid}.csv", index=False)
        (out / "gold/sql" / f"{iid}.sql").write_text(x["sql"].strip() + "\n")
        doc, k = None, knowledge(x.get("domain_knowledge"))
        if k:
            doc = f"{iid}.md"
            (out / "documents" / doc).write_text(k + "\n")
        questions.append({"instance_id": iid, "db": x["db"], "question": x["question"].strip(),
                          "external_knowledge": doc, "source": "beaver",
                          "split": "heldout" if x["db"] in held else "train",
                          "category": x["category"], "detailed_category": x["detailed_category"],
                          "engine_check": verdict})
        standards.append({"instance_id": iid, "condition_cols": [], "ignore_order": True})

    with open(out / "questions.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in questions)
    with open(out / "gold/eval.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in standards)
    report = {"questions": len(qs), "kept": len(questions), "dropped": dropped,
              "by_split": Counter(q["split"] for q in questions),
              "by_db_check": Counter(f"{q['db']}:{q['engine_check']}" for q in questions)}
    (out / "build_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
