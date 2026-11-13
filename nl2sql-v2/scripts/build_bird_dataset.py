#!/usr/bin/env python3
"""Build a judge-training question set from BIRD-Platinum (ReViSQL's corrected
sample of BIRD train) in the layout nl2sql/config.py reads under NL2SQL_DATASET_DIR,
so the agent, the scorer, the judge scripts and the enrichment scripts run on it
unchanged.

Dropped: databases in --deny (same data as a Spider2 local DB; see
check_db_overlap.py), items graded "subset" (the Spider2 scorer has no equivalent),
questions close to one of the 135 Spider2 local questions, gold SQL that fails,
times out, returns no rows or more than --max-rows rows, gold whose rows are
arbitrary (the result changes when SQLite scans tables in reverse order, or a LIMIT
cuts through tied rows), and gold whose answer depends on the engine: the gold runs
on SQLite, as in BIRD, but the agent runs DuckDB, so an item is dropped when DuckDB
runs the same SQL and the scorer rejects its result.

Split by database: a seeded --heldout-frac of the questions, as whole databases, is
held out for validation and never trained on. The split is written once to
<out>/db_split.json and reused by later builds and by every other training source.

Usage (from nl2sql-v2/):
    uv run python scripts/build_bird_dataset.py \\
        --items <ReViSQL>/data/bird-verified-train.json,<ReViSQL>/data/bird-verified-val.json \\
        --bird-dbs <BIRD>/train/train_databases --deny scripts/judge_data_deny.json \\
        --out /data/user_data/$USER/judge-data/bird_plat
then export NL2SQL_DATASET_DIR=<out> for run_benchmark.py and the enrichment scripts.
"""

import argparse
import difflib
import json
import random
import re
import sqlite3
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import SPIDER2_LITE
from nl2sql.db import Database
from nl2sql.eval import _csv_roundtrip, compare_dataframes

PREFIX = "bplat_"


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def spider2_questions() -> list[tuple[str, list[str], set]]:
    out = []
    for line in open(SPIDER2_LITE / "spider2-lite.jsonl"):
        q = json.loads(line)
        if q["instance_id"].startswith("local"):
            t = tokens(q["question"])
            out.append((q["instance_id"], t, {tuple(t[i:i + 8]) for i in range(len(t) - 7)}))
    return out


def near_spider2(question: str, s2) -> str | None:
    """The Spider2 local question this one shares an 8-word run with, or reads
    almost the same as (token similarity >= 0.75)."""
    t = tokens(question)
    grams = {tuple(t[i:i + 8]) for i in range(len(t) - 7)}
    for iid, st, sgrams in s2:
        if grams & sgrams:
            return iid
        sm = difflib.SequenceMatcher(None, t, st, autojunk=False)
        if sm.real_quick_ratio() >= 0.75 and sm.quick_ratio() >= 0.75 and sm.ratio() >= 0.75:
            return iid
    return None


def ignore_order_for(grading: str) -> bool | None:
    """BIRD-Platinum grading method -> Spider2 ignore_order; None = no equivalent."""
    g = grading.strip()
    return {"set": True, "multiset": True, "list": False}.get(g)


def sqlite_rows(db_path: Path, sql: str, timeout_s: float, n: int, reverse=False):
    """(column names, first n rows). reverse: scan tables in the opposite order
    (SQLite's reverse_unordered_selects), which changes which tied row comes first."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    con.execute(f"PRAGMA reverse_unordered_selects = {int(reverse)}")
    deadline = time.time() + timeout_s
    con.set_progress_handler(lambda: time.time() > deadline, 10_000)
    try:
        cur = con.execute(sql)
        return [d[0] for d in cur.description or []], cur.fetchmany(n)
    finally:
        con.close()


def run_gold(db_path: Path, sql: str, timeout_s: float, max_rows: int, reverse=False):
    try:
        cols, rows = sqlite_rows(db_path, sql, timeout_s, max_rows + 1, reverse)
    except sqlite3.OperationalError as e:
        return None, "gold_timeout" if "interrupted" in str(e) else f"gold_error: {e}"[:200]
    except sqlite3.Error as e:
        return None, f"gold_error: {e}"[:200]
    if not rows:
        return None, "gold_empty"
    if len(rows) > max_rows:
        return None, "gold_too_many_rows"
    seen = Counter()  # SELECT a.name, b.name: rename repeats as read_csv does (name, name.1)
    names = []
    for c in cols:
        names.append(f"{c}.{seen[c]}" if seen[c] else c)
        seen[c] += 1
    return pd.DataFrame(rows, columns=names), ""


def ties_at_limit(sql: str, run, dialect: str = "sqlite") -> bool:
    """True when an ORDER BY ... LIMIT k in the gold (outer query or a subquery that
    runs on its own) cuts between rows equal on every ORDER BY key, so which rows
    come back is arbitrary. Probes each such SELECT with its keys appended as
    columns and LIMIT k + 1. run(sql, n) returns the first n rows as tuples."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return False
    for sel in list(tree.find_all(exp.Select)):
        order, limit = sel.args.get("order"), sel.args.get("limit")
        if not order or not limit or not str(limit.expression.name).isdigit() \
                or int(limit.expression.name) < 1:
            continue
        k, projs = int(limit.expression.name), sel.expressions
        aliases = {p.alias: p.unalias() for p in projs if p.alias}
        keys = []
        for o in order.expressions:
            e = o.this
            if isinstance(e, exp.Literal) and e.is_int and 0 < int(e.name) <= len(projs):
                e = projs[int(e.name) - 1].unalias()  # ORDER BY 2
            elif isinstance(e, exp.Column) and not e.table and e.name in aliases:
                e = aliases[e.name]                   # ORDER BY an output alias
            keys.append(e.copy())
        probe = sel.copy()
        probe.set("expressions", [p.copy() for p in projs]
                  + [kx.as_(f"__k{i}") for i, kx in enumerate(keys)])
        try:
            rows = run(probe.limit(k + 1).sql(dialect=dialect), k + 1)
        except Exception:
            continue  # correlated, or needs an outer CTE: cannot run alone
        if len(rows) > k and rows[k - 1][-len(keys):] == rows[k][-len(keys):]:
            return True
    return False


def to_duckdb(sql: str) -> str | None:
    try:
        import sqlglot
        return sqlglot.transpile(sql, read="sqlite", write="duckdb")[0]
    except Exception:
        return None


def engine_check(db_path: Path, sql: str, gold_df, ignore_order: bool,
                 timeout_s: float) -> str:
    """'disagrees' when DuckDB runs the gold SQL (as written, else sqlglot's DuckDB
    translation) and the scorer rejects its result against SQLite's; NULL sort
    order and tie-breaking are the usual causes. SQLite's LIKE ignores case and
    DuckDB's does not, so a mismatch is retried with ILIKE first: the agent can
    reach that answer, it is not ambiguous. 'unverified' when DuckDB runs neither."""
    gold = _csv_roundtrip(gold_df.copy())
    db = Database(db_path)

    def agrees(s):
        duck, _ = db.query_preview(s, 1, 100_000, timeout_s=timeout_s)
        return compare_dataframes(_csv_roundtrip(duck), gold, ignore_order=ignore_order)

    try:
        for s in (sql, to_duckdb(sql)):
            if s is None:
                continue
            try:
                if agrees(s):
                    return "agrees"
            except Exception:
                continue
            if not re.search(r"\bLIKE\b", s, re.I):
                return "disagrees"
            try:
                return "agrees" if agrees(re.sub(r"\bLIKE\b", "ILIKE", s, flags=re.I)) \
                    else "disagrees"
            except Exception:
                return "disagrees"
        return "unverified"
    finally:
        db.close()


def split_dbs(counts: Counter, frac: float, seed: int) -> list[str]:
    """Whole databases, in seeded order, until they hold frac of the questions."""
    order = sorted(counts)
    random.Random(seed).shuffle(order)
    held, n = [], 0
    for db in order:
        if n >= frac * sum(counts.values()):
            break
        held.append(db)
        n += counts[db]
    return sorted(held)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True, help="comma-separated BIRD-Platinum json files")
    ap.add_argument("--bird-dbs", required=True, help="BIRD train_databases (<db>/<db>.sqlite)")
    ap.add_argument("--deny", required=True, help="json: database -> why it is excluded")
    ap.add_argument("--out", required=True)
    ap.add_argument("--heldout-frac", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-rows", type=int, default=2000, help="largest Spider2 local gold result")
    ap.add_argument("--gold-timeout", type=float, default=120.0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    out = Path(args.out)
    deny = {k: v for k, v in json.loads(Path(args.deny).read_text()).items()
            if not k.startswith("_")}

    items = []
    for f in args.items.split(","):
        split_name = "val" if "val" in Path(f).stem else "train"
        items += [dict(x, platinum_split=split_name) for x in json.load(open(f))]
    print(f"{len(items)} BIRD-Platinum items")

    dropped, keep = Counter(), []
    s2 = spider2_questions()
    for x in items:
        iid = PREFIX + str(x["question_id"])
        x["instance_id"] = iid
        if x["db_id"] in deny:
            dropped["denied_db"] += 1
        elif ignore_order_for(x["grading_method"]) is None:
            dropped["grader_not_supported"] += 1
        elif near := near_spider2(x["question"], s2):
            dropped["near_spider2_question"] += 1
            print(f"  {iid} reads like {near}: {x['question'][:100]}")
        elif not (Path(args.bird_dbs) / x["db_id"] / f"{x['db_id']}.sqlite").exists():
            dropped["db_missing"] += 1
        else:
            keep.append(x)

    split_path = out / "db_split.json"
    if split_path.exists():
        split = json.loads(split_path.read_text())
        print(f"reusing {split_path}")
    else:
        counts = Counter(x["db_id"] for x in keep)
        held = split_dbs(counts, args.heldout_frac, args.seed)
        split = {"seed": args.seed, "heldout_frac": args.heldout_frac, "heldout": held,
                 "train": sorted(set(counts) - set(held)), "denied": deny}
        out.mkdir(parents=True, exist_ok=True)
        split_path.write_text(json.dumps(split, indent=1) + "\n")
    held = set(split["heldout"])
    unassigned = {x["db_id"] for x in keep} - held - set(split["train"])
    if unassigned:
        raise SystemExit(f"databases missing from {split_path}: {sorted(unassigned)} "
                         "(add them to train or heldout by hand, or delete the file to re-split)")

    for d in ("databases", "documents", "gold/exec_result", "gold/sql", "dce/src/databases"):
        (out / d).mkdir(parents=True, exist_ok=True)
    dbs = sorted({x["db_id"] for x in keep})
    for db in dbs:
        link = out / "databases" / f"{db}.sqlite"
        if not link.exists():
            link.symlink_to((Path(args.bird_dbs) / db / f"{db}.sqlite").resolve())
        (out / "dce/src/databases" / f"{db}.yaml").write_text(
            f"type: sqlite\nname: {db}\nconnection:\n  database_path: {link.absolute()}\n")
    if not (out / "dce/dce.ini").exists():
        (out / "dce/dce.ini").write_text(f"[DEFAULT]\nproject-id = {uuid.uuid4()}\n")

    def gold(x):
        path = out / "databases" / f"{x['db_id']}.sqlite"
        ignore_order = ignore_order_for(x["grading_method"])
        df, err = run_gold(path, x["SQL"], args.gold_timeout, args.max_rows)
        if df is None:
            return None, err, ""
        rev, _ = run_gold(path, x["SQL"], args.gold_timeout, args.max_rows, reverse=True)
        if rev is not None and not compare_dataframes(
                _csv_roundtrip(rev), _csv_roundtrip(df.copy()), ignore_order=ignore_order):
            return None, "gold_order_dependent", ""  # arbitrary rows decide it
        if ties_at_limit(x["SQL"], lambda s, n: sqlite_rows(path, s, args.gold_timeout, n)[1]):
            return None, "gold_tie_at_limit", ""
        engine = engine_check(path, x["SQL"], df, ignore_order, args.gold_timeout)
        return (None, "engine_disagrees", engine) if engine == "disagrees" else (df, "", engine)

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(gold, keep))
    engine_counts = Counter(e for _, _, e in results if e)
    print(f"gold executed in {time.time() - t0:.0f}s; DuckDB vs SQLite: {dict(engine_counts)}")

    questions, standards, errors = [], [], []
    for x, (df, err, _) in zip(keep, results):
        iid = x["instance_id"]
        if df is None:
            dropped[err.split(":")[0]] += 1
            errors.append({"instance_id": iid, "db": x["db_id"], "reason": err})
            continue
        df.to_csv(out / "gold/exec_result" / f"{iid}.csv", index=False)
        (out / "gold/sql" / f"{iid}.sql").write_text(x["SQL"].strip() + "\n")
        doc = None
        if (x.get("evidence") or "").strip():
            doc = f"{iid}.md"
            (out / "documents" / doc).write_text(x["evidence"].strip() + "\n")
        questions.append({"instance_id": iid, "db": x["db_id"], "question": x["question"].strip(),
                          "external_knowledge": doc, "source": "bird_platinum",
                          "split": "heldout" if x["db_id"] in held else "train",
                          "platinum_split": x["platinum_split"]})
        standards.append({"instance_id": iid, "condition_cols": [],
                          "ignore_order": ignore_order_for(x["grading_method"])})

    for path, rows in ((out / "questions.jsonl", questions), (out / "gold/eval.jsonl", standards)):
        others = []  # rows from other sources (generate_trap_items.py) survive a rebuild
        if path.exists():
            others = [r for r in map(json.loads, open(path))
                      if not r["instance_id"].startswith(PREFIX)]
        with open(path, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows + others)
    by_split = Counter(r["split"] for r in questions)
    report = {"items": len(items), "kept": len(questions), "by_split": by_split,
              "dropped": dropped, "engine_check": engine_counts,
              "databases": {"train": len(split["train"]), "heldout": len(split["heldout"])},
              "errors": errors}
    (out / "build_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"kept {len(questions)} ({dict(by_split)}) on {len(dbs)} databases; "
          f"dropped {dict(dropped)} -> {out}")


if __name__ == "__main__":
    main()
