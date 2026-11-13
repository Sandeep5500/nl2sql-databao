#!/usr/bin/env python3
"""Write trap questions: SQL-first items built on the sites from profile_traps.py,
kept only when execution shows the question is well posed and the trap bites.

Per item (any stage can reject it; every attempt is logged with its reason):
 1. writer: from a trap site, three analytic patterns and the tables involved, a model
    writes gold_sql, careless_sql (the query a hurried analyst writes, which falls into
    the trap) and a one-sentence intent; with --style complex, a multi-step analysis
    (a chain of CTEs over several tables, as long as Spider2's agent SQL) around the trap;
 2. execution, on DuckDB like the agent: gold runs, returns 1..--max-rows rows, gives
    the same result twice and has no LIMIT through tied rows (with --style complex, it
    has at least --min-ctes CTEs); careless runs and the scorer rejects its result
    against the gold's;
 3. question writer: a model writes the question from the gold SQL, intent and result;
 4. blind solve: a solver shown only the question and the schema reaches the gold
    result (scorer) in one of --solver-samples tries;
 5. adjudication, both presentation orders: a model shown the question, gold and
    careless says which answers it; dropped when it picks careless both times;
 6. negatives: sql_mutations variants of the gold that the scorer rejects are stored
    beside the careless query, for rare error types the agent's own runs miss.

Accepted items are appended to the question set (questions.jsonl, gold/, eval.jsonl)
as trap_<db>_<hash> (cplx_<db>_<hash>, source "complex", with --style complex), with
their database's split from db_split.json; details go to
traps/items/<id>.json and every attempt to traps/attempts.jsonl.

Usage (NL2SQL_DATASET_DIR set; OpenAI-compatible endpoints; the question writer,
solver and adjudicator default to the writer):
    uv run python scripts/generate_trap_items.py --n-items 100 \\
        --writer-endpoint http://<node>:<port>/v1 --writer-model <model> \\
        [--question-endpoint ... --question-model ...] [--solver-endpoint ... --solver-model ...]
"""

import argparse
import csv
import hashlib
import io
import itertools
import json
import os
import random
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import (DATASET_DIR, EVAL_JSONL, GOLD_EXEC_DIR, GOLD_SQL_DIR,
                           QUESTIONS_FILE, SQLITE_DIR)
from nl2sql.db import Database
from nl2sql.eval import _csv_roundtrip, compare_dataframes
from build_bird_dataset import near_spider2, spider2_questions, ties_at_limit
from run_benchmark import schema_overview
from select_answer import ask_text, result_preview
from profile_traps import keyref
from sql_mutations import discriminating, mutants
import select_answer

PATTERNS = [
    "share of a total, as a percentage (a part divided by the whole)",
    "a rate per entity (a total divided by the number of distinct entities)",
    "the top k entities by an aggregated measure, keeping every entity tied at the cutoff",
    "the top entry within each group (e.g. the best item in each category)",
    "change from one period to the next (e.g. year over year)",
    "a running total over time",
    "each group compared with the overall average",
    "entities whose related rows meet a condition (counted or listed)",
    "the average of per-entity totals (aggregate first, then average)",
]

WRITER_PROMPT = """You are writing one question for a benchmark of hard analytics \
questions over SQL databases, starting from the SQL. The data is in SQLite and is \
queried with DuckDB SQL.

Database: {db}
{overview}

Tables around the trap:
{describes}
{descriptions}
A fact about this data that makes a plausible query wrong:
{fact}

Write two DuckDB queries for one realistic business question about this data.
- gold_sql answers the question correctly given the fact above. {shape} \
Return 1-30 rows. The result must be deterministic: no LIMIT that cuts through tied \
values (keep the ties, or order by enough columns to separate them) and no arbitrary \
picks. Every output column must be something the question asks for; round non-integer \
numbers to 2 decimals.
- careless_sql is the query a capable but hurried analyst would write for the same \
question and that goes wrong because of the fact above. It must look reasonable, not \
like a strawman, and return a different result.
- intent is one sentence saying exactly what gold_sql returns: which rows count, what \
is aggregated at which level, how ties and NULLs are handled, and the output columns \
in order.

Reply with JSON only: {{"gold_sql": "...", "careless_sql": "...", "intent": "..."}}"""

SHAPES = {
    "trap": "Use one of these patterns: {patterns}. Join 2-4 tables, with CTEs where natural "
            "(about 100-350 tokens).",
    # Spider2's right-vs-wrong pairs have a median of 4 CTEs and 3 joins (1,266 characters of
    # SQL) against 0 and 1 in the BIRD-based training pairs, where tuning did not transfer
    "complex": "Make it a multi-step analysis that chains two of these patterns: {patterns}. "
               "Write it as 3-6 CTEs, each one step of the analysis (filter, aggregate per "
               "entity, compare or rank, combine), over 3-5 tables: the tables above and "
               "others from the list of all tables (about 250-600 tokens). End with a step "
               "that keeps the result to at most 20 rows (a top k with ties, a filter, or one "
               "row per member of a small group).",
}
WORDS = {"trap": "30-80", "complex": "40-100"}

QUESTION_PROMPT = """Below is a SQL query over the {db} database and what it computes. \
Write the question a business analyst would ask that this query answers exactly.

What it computes: {intent}
SQL:
{sql}
First rows of its result:
{preview}
{descriptions}
Rules:
- {words} words of plain business language. No SQL keywords, and no table or column names \
unless they read as ordinary words.
- A careful reader must be able to arrive at exactly this result: state the filters and \
time range, what is counted or summed and per what, how ties are treated, any rounding, \
and which output columns to return in which order.
- Do not explain how to compute it and do not warn about pitfalls in the data.

Reply with JSON only: {{"question": "..."}}"""

SOLVER_PROMPT = """Answer the question with one DuckDB SQL query over this SQLite \
database.

Database: {db}
{overview}

Tables:
{describes}
{descriptions}
Question: {question}

Reply with JSON only: {{"sql": "..."}}"""

SPIDER2 = spider2_questions()  # the 135 local questions, for the near-duplicate check

ADJUDICATE_PROMPT = """Below are a business question and two SQL queries over the same \
database, with their results. Both run without errors. Decide which query answers the \
question as it is written.

Question: {question}

Query A:
{sql_a}
Result A:
{res_a}

Query B:
{sql_b}
Result B:
{res_b}

Reply with JSON only: {{"answer": "A" or "B", "reason": "<one sentence>"}}"""


def fact_text(s: dict) -> str:
    k = s["kind"]
    if "child" in s and "parent_keys" in s:
        on = f"{keyref(s['child'], s['child_cols'])} = {keyref(s['parent'], s['parent_keys'])}"
    if k == "fanout":
        return (f"Each {s['parent']} row matches on average {s['avg_children']} {s['child']} "
                f"rows (up to {s['max_children']}) through {on}. A query that joins {s['parent']} to "
                f"{s['child']} and then sums, averages or counts {s['parent']} values"
                + (f" (e.g. {', '.join(s['parent_measures'][:4])})" if s["parent_measures"] else "")
                + f" counts each {s['parent']} row once per matching {s['child']} row.")
    if k == "tie_at_cutoff":
        return (f"Ranking {s['parent']} rows by their number of {s['child']} rows (through "
                f"{on}) gives tied counts at the top-k cutoffs "
                f"k = {s['tied_at_k']} (largest counts: {s['top_counts']}). LIMIT k after "
                "ORDER BY keeps an arbitrary subset of the tied rows.")
    if k == "shared_name":
        ex = "; ".join(f"'{n}' has {c} different {s['id_column']} values" for n, c in s["examples"][:3])
        return (f"In {s['table']}, {s['names_with_several_ids']} {s['name_column']} values are "
                f"shared by several {s['id_column']}s ({ex}). Grouping or joining by "
                f"{s['name_column']} merges different entities.")
    if k == "null_or_zero":
        return (f"{s['table']}.{s['column']} is NULL in {s['nulls']} of {s['rows']} rows and 0 "
                f"in {s['zeros']}. AVG skips NULLs, COUNT({s['column']}) differs from COUNT(*), "
                "and a ratio with it as the denominator divides by zero or NULL.")
    if k == "overlapping":
        pairs = "; ".join(f"'{a}' is inside '{b}'" for a, b in s["pairs"][:4])
        return (f"{s['table']}.{s['column']} has values that contain one another ({pairs}). A "
                "filter with LIKE '%value%' or case-insensitive matching picks up more "
                "categories than the one meant.")
    if k == "orphan_rows":
        return (f"{s['orphan_rows']} rows of {s['child']} match no {s['parent']} row through "
                f"{on}. Counting {s['parent']} entities from "
                f"{s['child']} alone includes them; counting through {s['parent']} does not.")
    if k == "lookalike_columns":
        pairs = "; ".join(f"{a} and {b} differ in {n} of {m} rows" for a, b, n, m in s["columns"][:4])
        via = f", joined through {s['via']}" if s.get("via") else ""
        return (f"Columns that could each answer the same question hold different values{via}: "
                f"{pairs}. A query that takes the nearer or more obvious column answers a "
                "different question.")
    if k == "mixed_dates":
        shapes = ", ".join(f"'{ex}' ({round(100 * share)}%)" for _, share, ex in s["shapes"])
        return (f"{s['table']}.{s['column']} holds dates as text in several formats: {shapes}. "
                "Date functions or string comparisons that assume one format silently drop "
                "or misorder rows.")
    raise ValueError(k)


def site_tables(s: dict) -> list[str]:
    return [t for t in (s.get("parent"), s.get("child"), s.get("table")) if t]


def bird_descriptions(db_path: Path, tables: list[str]) -> str:
    """BIRD's human-written column descriptions (database_description/<table>.csv next
    to the SQLite file), for the writers only; the agent never sees them."""
    d = Path(os.path.realpath(db_path)).parent / "database_description"
    lines = []
    for t in tables:
        f = next((p for p in d.glob("*.csv") if p.stem.lower() == t.lower()), None)
        if f is None:
            continue
        text = f.read_bytes().decode("utf-8", "replace").lstrip("﻿")
        for r in csv.DictReader(io.StringIO(text)):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            desc = r.get("column_description") or r.get("column_name") or ""
            vals = r.get("value_description") or ""
            if desc or vals:
                lines.append(f"  {t}.{r.get('original_column_name', '')}: {desc}"
                             + (f" ({' '.join(vals.split())[:200]})" if vals else ""))
    return ("\nColumn descriptions from the database's documentation:\n" + "\n".join(lines) + "\n"
            if lines else "")


class ServerDown(BaseException):
    """A role's server went away or now serves another model: the attempt is not logged and
    reruns later. A BaseException, so the stages' own error handling lets it through."""


class Roles:
    def __init__(self, args):
        from openai import OpenAI
        self.cfg = {}
        for role in ("writer", "question", "solver", "adjudicator"):
            ep = getattr(args, f"{role}_endpoint") or args.writer_endpoint
            model = getattr(args, f"{role}_model") or args.writer_model
            # comma-separated endpoints serving the same model: calls are spread over them
            self.cfg[role] = ([OpenAI(base_url=e, api_key="EMPTY", timeout=2400)
                               for e in ep.split(",")], model)
        self.max_tokens = args.max_tokens
        self.calls = itertools.count()

    def ask(self, role: str, prompt: str, temp: float) -> dict:
        from openai import APIConnectionError, NotFoundError
        clients, model = self.cfg[role]
        client = clients[next(self.calls) % len(clients)]
        try:
            text = ask_text(client, model, prompt, temp, self.max_tokens)
        except (APIConnectionError, NotFoundError) as e:
            raise ServerDown(f"{role}: {e}") from e
        # the first JSON object in the reply: writers sometimes add text with braces after it,
        # which a match up to the last brace would include ("Extra data")
        for m in re.finditer(r"\{", text):
            try:
                return json.JSONDecoder().raw_decode(text[m.start():])[0]
            except json.JSONDecodeError:
                continue
        raise ValueError(f"no JSON in reply: {text[-120:]!r}")


def cte_count(sql: str) -> int:
    try:
        import sqlglot
        from sqlglot import exp
        return len(list(sqlglot.parse_one(sql, read="duckdb").find_all(exp.CTE)))
    except Exception:
        return 0


def matches(pred, gold) -> bool:
    return compare_dataframes(_csv_roundtrip(pred.copy()), _csv_roundtrip(gold.copy()),
                              ignore_order=True)


def same(a, b) -> bool:
    return len(a) == len(b) and matches(a, b) and matches(b, a)


def make_item(site: dict, db_name: str, seed: int, roles: Roles, args) -> dict:
    rng = random.Random(seed)
    rec = {"db": db_name, "site": site, "seed": seed}
    db = Database(SQLITE_DIR / f"{db_name}.sqlite")

    def run(sql):
        return db.query_preview(sql, 1, args.max_rows + 1, timeout_s=args.timeout)[0]

    def rows(sql, n):
        df = run(sql).head(n)
        return [tuple(None if v != v else v for v in r)  # NaN -> None, so NULL ties compare
                for r in df.astype(object).itertuples(index=False, name=None)]

    def reject(stage, reason):
        rec.update(stage=stage, accepted=False, reason=" ".join(str(reason).split())[:300])
        return rec

    try:
        tables = site_tables(site)
        overview = schema_overview(db)
        describes = "\n\n".join(db.describe_table(t, sample_rows=3) for t in tables)
        descriptions = bird_descriptions(SQLITE_DIR / f"{db_name}.sqlite", tables)
        rec["patterns"] = patterns = rng.sample(PATTERNS, 3)
        if args.style == "complex":
            rec.update(prefix="cplx", source="complex")
        gold = careless = None

        def check():  # (stage, reason) when the draft fails execution, else None
            nonlocal gold, careless
            if not (gold_sql and careless_sql and intent):
                return "writer", "writer_incomplete"
            try:
                gold = run(gold_sql)
            except Exception as e:
                return "execution", f"gold_error: {e}"
            if gold.empty or len(gold) > args.max_rows:
                return "execution", f"gold_rows_{len(gold)}"
            if not same(gold, run(gold_sql)):
                return "execution", "gold_nondeterministic"
            if ties_at_limit(gold_sql, rows, dialect="duckdb"):
                return "execution", "gold_tie_at_limit"
            if args.min_ctes and cte_count(gold_sql) < args.min_ctes:
                return "execution", f"gold_too_simple: {cte_count(gold_sql)} CTEs"
            try:
                careless = run(careless_sql)
            except Exception as e:
                return "execution", f"careless_error: {e}"
            if matches(careless, gold):
                return "execution", "trap_does_not_bite"
            return None

        prompt = WRITER_PROMPT.format(
            db=db_name, overview=overview, describes=describes, descriptions=descriptions,
            fact=fact_text(site), shape=SHAPES[args.style].format(patterns="; ".join(patterns)))
        rec["writer_retries"] = []
        for attempt in range(args.writer_retries + 1):
            try:
                w = roles.ask("writer", prompt, 0.7)
            except Exception as e:
                return reject("writer", f"writer_failed: {e}")
            gold_sql, careless_sql, intent = (str(w.get(k) or "").strip()
                                              for k in ("gold_sql", "careless_sql", "intent"))
            rec.update(gold_sql=gold_sql, careless_sql=careless_sql, intent=intent)
            failed = check()
            if not failed:
                break
            if attempt == args.writer_retries:
                return reject(*failed)
            # most first drafts of long SQL fail on a name, a type or the row count, and
            # the writer fixes them when shown the error
            rec["writer_retries"].append(" ".join(failed[1].split())[:300])
            prompt = (prompt + f"\n\nYour previous reply:\n{json.dumps(w)}\nIt was rejected: "
                      f"{' '.join(failed[1].split())[:400]}\nFix it, and reply with the full JSON again.")
        rec["gold_rows"], rec["careless_rows"] = len(gold), len(careless)

        try:
            question = str(roles.ask("question", QUESTION_PROMPT.format(
                db=db_name, intent=intent, sql=gold_sql, preview=result_preview(gold),
                words=WORDS[args.style],
                descriptions=descriptions), 0.7).get("question") or "").strip()
        except Exception as e:
            return reject("question", f"question_failed: {e}")
        if len(question.split()) < 8:
            return reject("question", "question_too_short")
        if near := near_spider2(question, SPIDER2):
            return reject("question", f"near_spider2_question: {near}")
        rec["question"] = question

        all_tables = db.list_tables()
        full = "\n\n".join(db.describe_table(t, sample_rows=3) for t in
                           tables + [t for t in all_tables if t not in tables])[:30_000]
        solve_prompt = SOLVER_PROMPT.format(
            db=db_name, overview=overview, describes=full,
            descriptions=bird_descriptions(SQLITE_DIR / f"{db_name}.sqlite", all_tables)[:8000],
            question=question)
        rec["solves"] = []
        for _ in range(args.solver_samples):
            prompt, sql, outcome = solve_prompt, "", "error"
            for _attempt in range(2):  # one retry with the error message
                try:
                    sql = str(roles.ask("solver", prompt, 0.7).get("sql") or "").strip()
                    df = run(sql)
                except Exception as e:
                    prompt = (solve_prompt + f"\n\nYour previous query:\n{sql}\nfailed with: "
                              f"{str(e)[:300]}\nReply with a corrected query, JSON only.")
                    continue
                outcome = ("gold" if matches(df, gold) else
                           "careless" if matches(df, careless) else "other")
                break
            rec["solves"].append({"outcome": outcome, "sql": sql})
            if outcome == "gold":
                break
        if not any(s["outcome"] == "gold" for s in rec["solves"]):
            return reject("solve", "blind_solve_failed")

        picks = []
        for first, second in (("gold", "careless"), ("careless", "gold")):
            q = {"gold": (gold_sql, gold), "careless": (careless_sql, careless)}
            try:
                a = str(roles.ask("adjudicator", ADJUDICATE_PROMPT.format(
                    question=question, sql_a=q[first][0], res_a=result_preview(q[first][1]),
                    sql_b=q[second][0], res_b=result_preview(q[second][1])), 0.0)
                    .get("answer", "")).strip().upper()
                picks.append(first if a == "A" else second if a == "B" else "none")
            except Exception:
                picks.append("none")
        rec["adjudication"] = picks
        if picks == ["careless", "careless"]:
            return reject("adjudicate", "adjudicator_prefers_careless")

        swaps = ({site["id_column"]: site["name_column"]} if site["kind"] == "shared_name" else None)
        rec["negatives"] = [{"operator": "careless", "sql": careless_sql, "rows": len(careless)}] \
            + discriminating(mutants(gold_sql, swaps=swaps), run, gold)
        rec["gold_csv"] = gold.to_csv(index=False)
        rec.update(stage="done", accepted=True, reason="")
        return rec
    except ServerDown as e:
        rec["server_down"] = True
        return reject(rec.get("stage", "unknown"), f"server_down: {e}")
    except Exception as e:
        return reject(rec.get("stage", "unknown"), f"crash: {e}")
    finally:
        db.close()


def item_id(rec: dict) -> str:
    return (f"{rec.get('prefix', 'trap')}_{rec['db']}_"
            f"{hashlib.sha1(rec['gold_sql'].encode()).hexdigest()[:8]}")


def write_item(rec: dict, split: str) -> str:
    iid = item_id(rec)
    (GOLD_EXEC_DIR / f"{iid}.csv").write_text(rec.pop("gold_csv"))
    (GOLD_SQL_DIR / f"{iid}.sql").write_text(rec["gold_sql"].strip() + "\n")
    with open(EVAL_JSONL, "a") as f:
        f.write(json.dumps({"instance_id": iid, "condition_cols": [], "ignore_order": True}) + "\n")
    with open(QUESTIONS_FILE, "a") as f:
        f.write(json.dumps({"instance_id": iid, "db": rec["db"], "question": rec["question"],
                            "external_knowledge": None, "source": rec.get("source", "trap"),
                            "split": split,
                            "trap_kind": rec["site"]["kind"]}) + "\n")
    rec["instance_id"] = iid
    return iid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-items", type=int, default=100, help="stop after this many accepted")
    ap.add_argument("--max-attempts", type=int, help="default: 4 x --n-items")
    for role in ("writer", "question", "solver", "adjudicator"):
        ap.add_argument(f"--{role}-endpoint", required=role == "writer")
        ap.add_argument(f"--{role}-model", required=role == "writer")
    ap.add_argument("--thinking", action="store_true", help="Qwen models reason first")
    ap.add_argument("--style", choices=sorted(SHAPES), default="trap")
    ap.add_argument("--writer-retries", type=int, default=0,
                    help="redrafts after a failed execution check, shown the error")
    ap.add_argument("--min-ctes", type=int, help="fewest CTEs in the gold (default: 3 for "
                    "--style complex, else 0)")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--solver-samples", type=int, default=2)
    ap.add_argument("--max-rows", type=int, default=50)
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds per query")
    ap.add_argument("--per-db", type=int, default=40, help="most attempts on one database")
    ap.add_argument("--attempts-per-site", type=int, default=3,
                    help="tries per site, each with its own seed and patterns")
    ap.add_argument("--splits", default="train,heldout", help="database splits to write for")
    ap.add_argument("--exclude-dbs", default="",
                    help="comma-separated databases to skip (language_corpus: a scan of its WITHOUT "
                         "ROWID tables ignores the query timeout and stalled a batch for an hour)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if not DATASET_DIR:
        raise SystemExit("set NL2SQL_DATASET_DIR to the question set to extend")
    select_answer.THINKING = args.thinking
    if args.min_ctes is None:
        args.min_ctes = 3 if args.style == "complex" else 0
    root = Path(DATASET_DIR)
    split_of = {db: s for s in ("train", "heldout")
                for db in json.loads((root / "db_split.json").read_text())[s]}
    want = set(args.splits.split(","))
    items_dir = root / "traps" / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    log_path = root / "traps" / "attempts.jsonl"

    tried = Counter()
    if log_path.exists():
        for r in map(json.loads, open(log_path)):
            tried[r["key"]] += 1
    by_kind = defaultdict(list)
    for f in sorted((root / "traps" / "sites").glob("*.json")):
        d = json.loads(f.read_text())
        if split_of.get(d["db"]) not in want or d["db"] in args.exclude_dbs.split(","):
            continue
        for s in d["sites"]:
            for n in range(args.attempts_per_site):
                kd = [d["db"], s, n] + ([args.style] if args.style != "trap" else [])
                key = hashlib.sha1(json.dumps(kd, sort_keys=True).encode()).hexdigest()[:12]
                by_kind[s["kind"]].append((d["db"], s, key))
    rng = random.Random(args.seed)
    for v in by_kind.values():
        rng.shuffle(v)
    queue, per_db = [], Counter()  # interleave kinds so each gets its share
    while any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind]:
                db, s, key = by_kind[kind].pop()
                if per_db[db] < args.per_db and not tried[key]:
                    queue.append((db, s, key))
                    per_db[db] += 1
    queue = queue[:args.max_attempts or 4 * args.n_items]
    print(f"{len(queue)} attempts queued over {len(per_db)} databases", flush=True)

    existing = {json.loads(l)["instance_id"] for l in open(QUESTIONS_FILE)}
    roles, lock, accepted, reasons = Roles(args), threading.Lock(), 0, Counter()
    with ThreadPoolExecutor(args.workers) as pool, open(log_path, "a") as log:
        futures = {pool.submit(make_item, s, db, int(key, 16) + args.seed, roles, args): (db, s, key)
                   for db, s, key in queue}
        for fut in as_completed(futures):
            if fut.cancelled():
                continue
            db, s, key = futures[fut]
            rec = fut.result()
            if rec.get("server_down"):  # not logged, so a later run retries this attempt
                reasons["server_down"] += 1
                continue
            with lock:
                if rec["accepted"] and item_id(rec) in existing:
                    rec.update(accepted=False, reason="duplicate_gold_sql")
                if rec["accepted"] and accepted < args.n_items:
                    iid = write_item(rec, split_of[db])
                    existing.add(iid)
                    (items_dir / f"{iid}.json").write_text(json.dumps(rec, indent=1, default=str))
                    accepted += 1
                reasons[rec["reason"].split(":")[0] or "accepted"] += 1
                log.write(json.dumps({"key": key, **{k: v for k, v in rec.items()
                                                      if k != "gold_csv"}}, default=str) + "\n")
                log.flush()
                print(f"[{sum(reasons.values())}/{len(queue)}] {db} {s['kind']}: "
                      f"{rec.get('instance_id') or rec['reason'][:80]}", flush=True)
            if accepted >= args.n_items:
                for f in futures:
                    f.cancel()  # queued attempts only; running ones finish unlogged
                break
    print(f"\naccepted {accepted}; outcomes {dict(reasons)}")


if __name__ == "__main__":
    main()
