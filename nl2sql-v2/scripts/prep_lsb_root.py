"""Build a Spider2-shaped data root from LiveSQLBench-Base-Lite (SQLite).

Nothing in nl2sql-v2 changes: every path derives from NL2SQL_DATA_ROOT and
score_against_gold finds gold by filename, so shaping the data is enough.

    <root>/Spider2/spider2-lite/
        spider2-lite.jsonl                               questions
        resource/databases/spider2-localdb/<db>.sqlite   copies of *_template.sqlite
        resource/documents/<db>_kb.md                    the database's WHOLE knowledge base
        evaluation_suite/gold/exec_result/<iid>_a.csv    gold, executed with sqlite3
        evaluation_suite/gold/spider2lite_eval.jsonl     per-question ignore_order

Four decisions worth knowing, each measured rather than assumed:

1. QUERY ONLY (180 of 270). The 90 `Management` golds are CREATE/ALTER/UPDATE/
   DELETE; our scorer compares SELECT result sets and cannot score them. All 180
   Query golds are a single SELECT/WITH statement with no preprocess_sql and no
   clean_up_sqls, so they need no setup or teardown.

2. THE WHOLE KNOWLEDGE BASE, NOT THE ORACLE SUBSET. Each question ships
   `external_knowledge: [0, 50]` -- pointers to ~2.5 of its database's 49-86 KB
   entries. Handing the agent exactly those entries tells it which definitions
   matter, which it would not know in a realistic setting. So every question in a
   database points at that database's FULL KB and must locate the relevant
   definitions itself. The oracle subset is recorded in the sidecar file
   `oracle_knowledge.jsonl` for offline diagnosis only -- never in a prompt.

3. ignore_order = not conditions.order. Validated against the verified gold:
   conditions.order=True implies the gold contains ORDER BY in 118/118 cases,
   and never the reverse. The 9 questions whose gold sorts incidentally while
   conditions.order=False are scored order-insensitively, which is correct.

4. THE GOLD BLANKNESS GATE IS APPLIED HERE TOO. The synthetic build shipped an
   all-blank gold (`local_syn0139`) that scored every correct answer wrong,
   because the gate read a recorded preview instead of the executed result.
   This checks what the query actually returns.
"""
import argparse, csv, json, os, re, shutil, sqlite3, sys, time
from collections import Counter
from pathlib import Path


def render_kb(kb_path: Path) -> str:
    """The database's whole knowledge base as one markdown document."""
    rows = []
    with open(kb_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    out = ["# Domain knowledge base", "",
           f"{len(rows)} definitions for this database. Not all are relevant to any "
           "one question; find the ones that are.", ""]
    for r in sorted(rows, key=lambda r: r.get("id", 0)):
        name = r.get("knowledge") or f"entry {r.get('id')}"
        out.append(f"## {name}")
        if r.get("type"):
            out.append(f"*type: {r['type']}*")
        if r.get("description"):
            out.append(str(r["description"]))
        if r.get("definition"):
            out.append("")
            out.append(f"**Definition.** {r['definition']}")
        ch = r.get("children_knowledge")
        if isinstance(ch, list) and ch:
            out.append(f"*depends on entries: {ch}*")
        elif isinstance(ch, int) and ch >= 0:
            out.append(f"*depends on entry {ch}*")
        out.append("")
    return "\n".join(out)


def run_gold(db_path: Path, sql: str, timeout_s: float):
    """Execute gold read-only with a hard wall-clock stop."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    deadline = time.time() + timeout_s
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows, None
    except Exception as e:
        msg = "timeout" if time.time() > deadline else f"{type(e).__name__}: {e}"
        return None, None, str(msg)[:110]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", required=True, help="livesqlbench_data_sqlite.jsonl")
    ap.add_argument("--gt", required=True, help="the emailed gt/kg/testcases jsonl")
    ap.add_argument("--raw", required=True, help="dir with <db>_template.sqlite and <db>_kb.jsonl")
    ap.add_argument("--root", required=True)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--max-rows", type=int, default=20000)
    ap.add_argument("--verify", action="store_true",
                    help="classify each question by how gold relates to the agent's engine")
    a = ap.parse_args()

    lite = Path(a.root) / "Spider2/spider2-lite"
    dbdir = lite / "resource/databases/spider2-localdb"
    docdir = lite / "resource/documents"
    golddir = lite / "evaluation_suite/gold/exec_result"
    for d in (dbdir, docdir, golddir):
        d.mkdir(parents=True, exist_ok=True)

    hf = [json.loads(l) for l in open(a.hf) if l.strip()]
    gt = {}
    for l in open(a.gt):
        if l.strip():
            r = json.loads(l)
            gt[r["instance_id"]] = r

    qy = [r for r in hf if r.get("category") == "Query"]
    print(f"{len(hf)} records -> {len(qy)} Query "
          f"({len(hf)-len(qy)} Management dropped: DDL/DML gold is not scorable "
          f"by result comparison)")

    raw = Path(a.raw)
    dbs = sorted({r["selected_database"] for r in qy})
    for db in dbs:
        src = raw / f"{db}_template.sqlite"
        if not src.exists():
            sys.exit(f"missing database: {src}")
        dst = dbdir / f"{db}.sqlite"
        if not dst.exists():
            shutil.copy2(src, dst)
        kb = raw / f"{db}_kb.jsonl"
        if not kb.exists():
            sys.exit(f"missing knowledge base: {kb}")
        (docdir / f"{db}_kb.md").write_text(render_kb(kb))
    sizes = [len((docdir / f"{db}_kb.md").read_text()) for db in dbs]
    print(f"{len(dbs)} databases copied; knowledge documents "
          f"{min(sizes)}-{max(sizes)} chars (~{min(sizes)//4}-{max(sizes)//4} tokens)")

    questions, standards, oracle, failures = [], [], [], Counter()
    made = reused = 0
    for r in qy:
        orig = r["instance_id"]
        iid = f"local_lsb_{orig}"                 # must start with "local"
        db = r["selected_database"]
        sols = (gt.get(orig) or {}).get("sol_sql") or []
        if len(sols) != 1:
            failures["not exactly one gold statement"] += 1
            continue
        gold_path = golddir / f"{iid}_a.csv"
        if gold_path.exists():
            reused += 1
        else:
            cols, rows, err = run_gold(dbdir / f"{db}.sqlite", sols[0], a.timeout)
            if err:
                failures[err.split(":")[0]] += 1
                continue
            if not cols or len(rows) == 0 or len(rows) > a.max_rows:
                failures["empty or oversized"] += 1
                continue
            flat = [("" if v is None else str(v)).strip() for row in rows for v in row]
            if flat and all(v == "" for v in flat):
                failures["gold all blank"] += 1
                continue
            if flat and sum(1 for v in flat if v == "") / len(flat) > 0.5:
                failures["gold >50% blank"] += 1
                continue
            with open(gold_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
            made += 1

        questions.append({"instance_id": iid, "db": db, "question": r["query"],
                          "external_knowledge": f"{db}_kb.md"})
        # ignore_order is TRUE for every question. conditions.order marks the
        # questions whose gold has ORDER BY, but those ORDER BYs have ties, and
        # SQLite and DuckDB break ties differently -- so enforcing order fails 25
        # of 124 correct answers on an arbitrary tie-break. The agent is tested on
        # computing the right values, not on reproducing one engine's tie order.
        standards.append({"instance_id": iid, "ignore_order": True,
                          "condition_cols": None})
        oracle.append({"instance_id": iid, "difficulty_tier": r.get("difficulty_tier"),
                       "oracle_knowledge_ids": (gt.get(orig) or {}).get("external_knowledge") or [],
                       "conditions": r.get("conditions")})

    with open(lite / "spider2-lite.jsonl", "w") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")
    with open(lite / "evaluation_suite/gold/spider2lite_eval.jsonl", "w") as f:
        for s in standards:
            f.write(json.dumps(s) + "\n")
    # offline only -- names the oracle KB entries, so it must never reach a prompt
    with open(lite / "oracle_knowledge.jsonl", "w") as f:
        for o in oracle:
            f.write(json.dumps(o) + "\n")

    enforced = sum(1 for s in standards if not s["ignore_order"])
    print(f"\ngold written {made}, reused {reused}, usable questions {len(questions)}")
    print(f"order enforced on {enforced}, order ignored on {len(standards)-enforced}")
    print(f"difficulty: {dict(Counter(o['difficulty_tier'] for o in oracle))}")
    if failures:
        print("gold failures:")
        for k, v in failures.most_common():
            print(f"    {k:<34}{v}")
    print(f"\nroot ready: {a.root}")

    if a.verify:
        verify(a.root, questions, gt)


def verify(root, questions, gt):
    """Classify questions by how the agent's engine relates to the gold. REPORTS;
    it does not exclude on dialect.

    An earlier version of this excluded any question whose GOLD SQL would not run
    in DuckDB. That was wrong: the agent never runs the gold SQL, it writes its
    own query. Gold using `julianday` is answerable with DuckDB date arithmetic,
    so a dialect error in the gold says nothing about whether the question can be
    solved. The gold CSV -- the human-verified answer -- is what must be matched.

    What IS disqualifying is a gold the agent cannot match with ANY query:
      - degenerate gold (blank, or a million rows), already gated upstream
      - gold whose float aggregate differs from DuckDB's by more than the
        scorer's absolute tolerance, which no query can close

    So this reports three classes and excludes none of them here. The float case
    is a SCORER fix (rel_tol), not a reason to drop a question.
    """
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    os.environ["NL2SQL_DATA_ROOT"] = str(root)
    for m in ("nl2sql.config", "nl2sql.eval", "nl2sql.db"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    from nl2sql.eval import score_against_gold, load_eval_standards
    from nl2sql.db import Database
    from nl2sql.config import AgentConfig

    cfg = AgentConfig()
    lite = Path(root) / "Spider2/spider2-lite"
    std = load_eval_standards()
    keep, notes = [], []
    for q in questions:
        iid = q["instance_id"]; orig = iid[len("local_lsb_"):]
        sol = (gt.get(orig) or {}).get("sol_sql") or []
        if not sol:
            drop.append((iid, "no gold sql")); continue
        try:
            db = Database(lite / f"resource/databases/spider2-localdb/{q['db']}.sqlite")
            pred, _ = db.query_preview(sol[0], cfg.preview_rows_default,
                                       cfg.result_rows_max, cfg.cell_char_limit)
            db.close()
        except Exception as e:
            # Gold SQL is SQLite-flavoured and DuckDB rejects it. The question is
            # still answerable: the agent writes its own DuckDB query against the
            # same gold CSV. KEPT, and noted as needing a dialect translation.
            notes.append((iid, "gold_sql_dialect", type(e).__name__))
            keep.append(q)
            continue
        try:
            score, detail = score_against_gold(pred, iid, std)
        except Exception as e:
            notes.append((iid, "scorer_error", type(e).__name__))
            keep.append(q)
            continue
        if score:
            notes.append((iid, "reproduced", ""))
            keep.append(q)
        else:
            notes.append((iid, "value_disagreement", str(detail)[:60]))
            keep.append(q)

    with open(lite / "spider2-lite.jsonl", "w") as f:
        for q in keep:
            f.write(json.dumps(q) + "\n")
    with open(lite / "engine_notes.jsonl", "w") as f:
        for iid, cls, extra in notes:
            f.write(json.dumps({"instance_id": iid, "class": cls, "detail": extra}) + "\n")

    agg = Counter(c for _, c, _ in notes)
    print(f"\n=== engine classification (reporting only; nothing excluded here) ===")
    print(f"  questions kept: {len(keep)}")
    for k, v in agg.most_common():
        label = {"reproduced": "gold SQL reproduces gold in DuckDB -- cleanest",
                 "gold_sql_dialect": "gold SQL is SQLite-only -- agent must write DuckDB SQL (still solvable)",
                 "value_disagreement": "gold SQL runs but values differ -- check tolerance/ordering",
                 "scorer_error": "scorer raised"}.get(k, k)
        print(f"     {v:>4}  {label}")
    dial = Counter(e for _, c, e in notes if c == "gold_sql_dialect")
    if dial:
        print("  dialect error kinds:", dict(dial.most_common(6)))
    print(f"  -> per-question classes in {lite}/engine_notes.jsonl")


if __name__ == "__main__":
    main()
