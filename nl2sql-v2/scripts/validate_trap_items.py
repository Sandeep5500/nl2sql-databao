#!/usr/bin/env python3
"""Check and admit hand-written items (written by people or agents rather than through
generate_trap_items.py's model endpoints): trap items, and "plain" hard questions with no
designed trap. The same execution gates, a blind-solve gate fed by solutions written
separately, optional stress-test and review results, and the same output as the generator.

Item lines (--items, comma-separated files):
    {"id", "db", "kind", "gold_sql", "careless_sql", "intent", "question"}
    (kind "plain": careless_sql may be empty)
Solution lines (--solutions, any number per id), from solvers that saw only the question
and the database: {"id", "sql"}
Stress lines (--stress, from stress_test_items.py): {"id", "status": agree|split|untested}
Review lines (--reviews): {"id", "verdict": gold_right|gold_wrong|ambiguous, "note"}

Gates: the gold runs on DuckDB as the agent does, returns 1..--max-rows rows, gives the same
result twice and the same result with DuckDB's common_subplan optimizer off (DuckDB 1.5.5
can merge scans of same-shaped tables; an item must not depend on that), and has no LIMIT
through tied rows; with --rounding-check, no value it rounds sits on a rounding boundary;
a trap's careless query runs, is equally stable, and the scorer rejects its result against
the gold's; the question has 30-120 words and does not read like a Spider2 local question;
with --solutions, a solution reaches the gold result; with --stress, the gold and the
solutions that matched it still agree on altered copies of the database. A reviewer's
gold_right clears a failed solve or a stress split; gold_wrong and ambiguous reject.

Usage (NL2SQL_DATASET_DIR set to the question set):
    python scripts/validate_trap_items.py --items items.jsonl                    # report only
    python scripts/validate_trap_items.py --items a.jsonl,b.jsonl --solutions s.jsonl \\
        [--stress st.jsonl] [--reviews rv.jsonl] [--rounding-check] --write
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import DATASET_DIR, QUESTIONS_FILE, SQLITE_DIR
from nl2sql.db import Database
from build_bird_dataset import near_spider2, spider2_questions, ties_at_limit
from generate_trap_items import item_id, matches, same, write_item
from sql_mutations import discriminating, mutants

KINDS = {"fanout", "tie_at_cutoff", "shared_name", "null_or_zero", "overlapping", "mixed_dates",
         "orphan_rows", "lookalike_columns", "grain", "plain"}


def rounding_boundary(sql: str, run) -> bool:
    """True when a value the gold rounds sits on a rounding boundary (84231.935 to two
    decimals): an equivalent query that adds in another order can round the other way, and
    the scorer then rejects it. Runs the gold with its ROUNDs removed and checks each output
    column against the precision of its own ROUND (found in the final SELECT, or through
    the alias of a rounded CTE column); columns it cannot trace get every precision used."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return False

    def digits_in(node) -> set:
        return {int(d.name) if d is not None and str(d.name).isdigit() else 0
                for d in (r.args.get("decimals") for r in node.find_all(exp.Round))}

    every = digits_in(tree)
    if not every:
        return False
    by_alias = {}
    for a in tree.find_all(exp.Alias):
        if digits_in(a.this):
            by_alias.setdefault(a.alias.lower(), set()).update(digits_in(a.this))
    outer = tree if isinstance(tree, exp.Select) else next(tree.find_all(exp.Select), None)
    per_col = []
    for p in (outer.expressions if outer is not None else []):
        if isinstance(p, exp.Star):
            break  # columns from here on cannot be traced
        d = digits_in(p)
        if not d and isinstance(p.unalias(), exp.Column):
            d = by_alias.get(p.unalias().name.lower(), set())
        per_col.append(d)
    try:
        df = run(tree.transform(lambda n: n.this if isinstance(n, exp.Round) else n)
                 .sql(dialect="duckdb"))
    except Exception:
        return False
    for i in range(df.shape[1]):
        digits = per_col[i] if i < len(per_col) else every
        for v in df.iloc[:, i]:
            if isinstance(v, float) and v == v and any(
                    abs((abs(v) * 10 ** n) % 1 - 0.5) < 1e-6 for n in digits):
                return True
    return False


def check(item: dict, s2, args) -> dict:
    """{"ok", "reason", and on success the gold and careless frames}."""
    out = {"id": item.get("id"), "ok": False, "reason": ""}
    plain = item.get("kind") == "plain"
    missing = [k for k in ("id", "db", "kind", "gold_sql", "careless_sql", "intent", "question")
               if not str(item.get(k) or "").strip() and not (plain and k == "careless_sql")]
    if missing:
        return {**out, "reason": f"missing {missing}"}
    if item["kind"] not in KINDS:
        return {**out, "reason": f"unknown kind {item['kind']}"}
    path = SQLITE_DIR / f"{item['db']}.sqlite"
    if not path.exists():
        return {**out, "reason": "unknown db"}
    cur, fix = Database(path), Database(path)
    fix.con.execute("SET disabled_optimizers='cte_inlining,common_subplan'")

    def run(db, sql):
        return db.query_preview(sql, 1, args.max_rows + 1, timeout_s=args.timeout)[0]

    def rows(sql, n):
        df = run(cur, sql).head(n)
        return [tuple(None if v != v else v for v in r)
                for r in df.astype(object).itertuples(index=False, name=None)]

    def fail(reason):
        return {**out, "reason": " ".join(str(reason).split())[:300]}

    try:
        g, c = item["gold_sql"], item["careless_sql"]
        try:
            gold = run(cur, g)
        except Exception as e:
            return fail(f"gold_error: {e}")
        if gold.empty or len(gold) > args.max_rows:
            return fail(f"gold_rows: {len(gold)} (need 1..{args.max_rows})")
        if not same(gold, run(cur, g)):
            return fail("gold_nondeterministic")
        if not same(gold, run(fix, g)):
            return fail("gold_engine_sensitive (changes with common_subplan off)")
        if ties_at_limit(g, rows, dialect="duckdb"):
            return fail("gold_tie_at_limit")
        if args.rounding_check and rounding_boundary(g, lambda s: run(fix, s)):
            return fail("gold_rounding_boundary (a rounded value sits on x.xx5)")
        careless = None
        if str(c or "").strip():
            try:
                careless = run(cur, c)
            except Exception as e:
                return fail(f"careless_error: {e}")
            try:
                if not same(careless, run(fix, c)):
                    return fail("careless_engine_sensitive")
            except Exception as e:
                return fail(f"careless_error: {e}")
            if matches(careless, gold):
                return fail("trap_does_not_bite (scorer accepts the careless result)")
        words = len(item["question"].split())
        if not 30 <= words <= 120:
            return fail(f"question_words: {words} (need 30..120)")
        if near := near_spider2(item["question"], s2):
            return fail(f"near_spider2_question: {near}")
        return {**out, "ok": True, "gold": gold, "careless": careless,
                "gold_rows": len(gold), "careless_rows": None if careless is None else len(careless)}
    finally:
        cur.close()
        fix.close()


def solve_outcomes(item: dict, sqls: list[str], gold, careless, args) -> list[dict]:
    db = Database(SQLITE_DIR / f"{item['db']}.sqlite")
    res = []
    try:
        for sql in sqls:
            try:
                df = db.query_preview(sql, 1, args.max_rows + 1, timeout_s=args.timeout)[0]
                outcome = ("gold" if matches(df, gold) else
                           "careless" if careless is not None and matches(df, careless)
                           else "other")
            except Exception as e:
                outcome = f"error: {' '.join(str(e).split())[:120]}"
            res.append({"outcome": outcome, "sql": sql})
    finally:
        db.close()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True, help="comma-separated item files")
    ap.add_argument("--solutions", help="comma-separated blind-solution files")
    ap.add_argument("--write", action="store_true", help="admit items that pass every gate")
    ap.add_argument("--max-rows", type=int, default=50)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--author", default="hand-written")
    ap.add_argument("--stress", help="comma-separated stress_test_items.py outputs")
    ap.add_argument("--reviews", help="comma-separated reviewer verdict files")
    ap.add_argument("--rounding-check", action="store_true",
                    help="reject golds that round a value sitting on x.xx5")
    ap.add_argument("--only-ids", help="file of item ids (one per line) to consider")
    ap.add_argument("--report", help="report path (default: next to the first items file)")
    args = ap.parse_args()
    if not DATASET_DIR:
        raise SystemExit("set NL2SQL_DATASET_DIR to the question set")
    root = Path(DATASET_DIR)
    split_of = {db: s for s in ("train", "heldout")
                for db in json.loads((root / "db_split.json").read_text())[s]}
    items = [json.loads(l) for f in args.items.split(",") for l in open(f) if l.strip()]
    if args.only_ids:
        keep = set(Path(args.only_ids).read_text().split())
        items = [it for it in items if it.get("id") in keep]
    sols = defaultdict(list)
    for f in (args.solutions or "").split(","):
        if f:
            for r in map(json.loads, (l for l in open(f) if l.strip())):
                if str(r.get("sql") or "").strip():
                    sols[r["id"]].append(r["sql"])

    def by_id(files, key):
        out = {}
        for f in (files or "").split(","):
            if f:
                for r in map(json.loads, (l for l in open(f) if l.strip())):
                    out[r["id"]] = r[key]
        return out

    stress, reviews = by_id(args.stress, "status"), by_id(args.reviews, "verdict")
    s2 = spider2_questions()
    existing = {json.loads(l)["instance_id"] for l in open(QUESTIONS_FILE)}
    seen_ids, verdicts, admitted = set(), Counter(), 0
    report = []
    for item in items:
        if item.get("id") in seen_ids:
            verdicts["duplicate_id"] += 1
            print(f"{item.get('id')}: FAIL duplicate id")
            continue
        seen_ids.add(item.get("id"))
        r = check(item, s2, args)
        if r["ok"] and item["db"] not in split_of:
            r = {**r, "ok": False, "reason": "db not in db_split.json"}
        rec = {"id": item["id"], "db": item.get("db"), "kind": item.get("kind"),
               "ok": r["ok"], "reason": r["reason"]}
        if r["ok"] and args.solutions:
            outs = solve_outcomes(item, sols.get(item["id"], []), r["gold"], r["careless"], args)
            rec["solves"] = outs
            if not any(o["outcome"] == "gold" for o in outs):
                rec.update(ok=False, reason="blind_solve_failed" if outs else "no_solution")
        if r["ok"]:  # stress and review act only on items that pass the execution gates
            if rec["ok"] and stress.get(item["id"]) == "split":
                rec.update(ok=False, reason="stress_split")
            verdict = reviews.get(item["id"])
            if verdict in ("gold_wrong", "ambiguous"):
                rec.update(ok=False, reason=f"review_{verdict}")
            elif verdict == "gold_right" and rec["reason"] in (
                    "blind_solve_failed", "no_solution", "stress_split"):
                rec.update(ok=True, reason="", cleared_by_review=rec["reason"])
            rec["stress"], rec["review"] = stress.get(item["id"]), verdict
        if rec["ok"] and args.write:
            plain = item["kind"] == "plain"
            full = {"db": item["db"], "site": {"kind": item["kind"]}, "gold_sql": item["gold_sql"],
                    "careless_sql": item.get("careless_sql") or "", "intent": item["intent"],
                    "question": item["question"], "author": args.author,
                    "source": "written" if plain else "trap", "prefix": "hard" if plain else "trap",
                    "source_id": item["id"], "solves": rec.get("solves", []),
                    "stress": rec.get("stress"), "review": rec.get("review"),
                    "gold_rows": r["gold_rows"], "careless_rows": r["careless_rows"],
                    "gold_csv": r["gold"].to_csv(index=False)}
            if item_id(full) in existing:
                rec.update(ok=False, reason="already_admitted")
            else:
                db = Database(SQLITE_DIR / f"{item['db']}.sqlite")
                try:
                    run = lambda s: db.query_preview(s, 1, args.max_rows + 1, timeout_s=args.timeout)[0]
                    careless = [] if r["careless"] is None else [
                        {"operator": "careless", "sql": item["careless_sql"], "rows": r["careless_rows"]}]
                    full["negatives"] = careless + discriminating(mutants(item["gold_sql"]), run, r["gold"])
                finally:
                    db.close()
                iid = write_item(full, split_of[item["db"]])
                existing.add(iid)
                (root / "traps" / "items").mkdir(parents=True, exist_ok=True)
                (root / "traps" / "items" / f"{iid}.json").write_text(json.dumps(full, indent=1, default=str))
                rec["instance_id"] = iid
                admitted += 1
        verdicts["pass" if rec["ok"] else rec["reason"].split(":")[0].split(" (")[0]] += 1
        report.append(rec)
        print(f"{rec['id']} [{rec['db']}, {rec['kind']}]: "
              f"{'PASS' if rec['ok'] else 'FAIL ' + rec['reason']}"
              + (f" -> {rec['instance_id']}" if rec.get("instance_id") else ""), flush=True)
    out = Path(args.report or Path(args.items.split(",")[0]).with_suffix(".report.json"))
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\n{len(report)} items: {dict(verdicts)}" + (f"; admitted {admitted}" if args.write else "")
          + f"\nreport: {out}")


if __name__ == "__main__":
    main()
