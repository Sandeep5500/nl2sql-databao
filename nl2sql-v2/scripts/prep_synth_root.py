"""Build a Spider2-shaped data root from main1k so the UNMODIFIED harness runs it.

Nothing in nl2sql-v2 changes. Every path the harness uses derives from
NL2SQL_DATA_ROOT, and score_against_gold finds gold purely by filename, so
shaping the data is enough:

    <root>/Spider2/spider2-lite/
        spider2-lite.jsonl                               questions
        resource/databases/spider2-localdb/<db>.sqlite   symlinks to synsql/filled
        resource/documents/                              empty
        evaluation_suite/gold/exec_result/<iid>_a.csv    gold, from sqlite3
        evaluation_suite/gold/spider2lite_eval.jsonl     ignore_order per question

instance_id is prefixed "local_" so it passes run_benchmark's
`if not iid.startswith("local")` filter without touching that code.

Defective gold is excluded (duplicate columns, constant-1 columns, all-zero
numerics) -- ~20% of the corpus, measured over the recorded previews.
Idempotent: existing gold CSVs are kept, so it can be re-run to extend N.
"""
import argparse, csv, io, json, os, re, sqlite3, sys, time
from collections import Counter
from pathlib import Path

NUM = re.compile(r"^-?\d+(\.\d+)?$")


def preview_defect(rec):
    """Return a defect label for a recorded gold preview, or None if clean."""
    try:
        rd = [r for r in csv.reader(io.StringIO(rec.get("gold_preview") or "")) if r]
    except Exception:
        return "unparsable preview"
    if len(rd) < 2:
        return "no preview"
    hdr, body = rd[0], [r for r in rd[1:] if len(r) == len(rd[0])]
    if not body:
        return "no preview"
    cols = list(zip(*body))
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            if cols[i] == cols[j] and any(v.strip() for v in cols[i]):
                return "duplicate column"
    for c in cols:
        if c and all(v.strip() == "1" for v in c):
            return "constant-1 column"
    num = [c for c in cols if c and all(NUM.match(v.strip() or "x") for v in c)]
    if num and all(all(float(v) == 0 for v in c) for c in num):
        return "all-zero numerics"
    return None


def run_gold(db_path, sql, timeout_s):
    """Execute gold with a hard wall-clock stop, so one slow query can't hang the run."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    deadline = time.time() + timeout_s
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows, None
    except Exception as e:
        msg = "timeout" if time.time() > deadline else f"{type(e).__name__}: {e}"
        return None, None, str(msg)[:90]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main1k", default="/home/juliep2/main1k.jsonl")
    ap.add_argument("--filled", default="/data/user_data/juliep2/synsql/filled")
    ap.add_argument("--root", default="/data/user_data/juliep2/synthroot")
    ap.add_argument("--n", type=int, default=150, help="clean questions to materialise")
    ap.add_argument("--timeout", type=float, default=20.0, help="seconds per gold query")
    ap.add_argument("--max-rows", type=int, default=20000)
    a = ap.parse_args()

    lite = Path(a.root) / "Spider2/spider2-lite"
    dbdir = lite / "resource/databases/spider2-localdb"
    golddir = lite / "evaluation_suite/gold/exec_result"
    for d in (dbdir, lite / "resource/documents", golddir):
        d.mkdir(parents=True, exist_ok=True)

    recs = [json.loads(l) for l in open(a.main1k)]
    ok = [r for r in recs if r.get("status") == "pass"]
    reasons = Counter()
    clean = []
    for r in ok:
        d = preview_defect(r)
        if d:
            reasons[d] += 1
        else:
            clean.append(r)
    print(f"main1k pass={len(ok)}  clean={len(clean)}  excluded={sum(reasons.values())}")
    for k, v in reasons.most_common():
        print(f"    excluded: {k:<22}{v}")

    # keep the hard/easy mix of the clean pool rather than taking the first N
    clean.sort(key=lambda r: (not r.get("hard"), r["id"]))
    hard = [r for r in clean if r.get("hard")]
    easy = [r for r in clean if not r.get("hard")]
    want_hard = min(len(hard), a.n // 2)
    chosen = hard[:want_hard] + easy[: a.n - want_hard]
    print(f"materialising {len(chosen)} ({want_hard} hard, {len(chosen)-want_hard} easy)")

    questions, standards, failures = [], [], Counter()
    made = skipped = 0
    for r in chosen:
        iid = f"local_{r['id']}"
        db_file = (r.get("provenance") or {}).get("db_file") or ""
        src = Path(a.filled) / db_file
        if not src.exists():
            failures["db missing"] += 1
            continue
        gold_path = golddir / f"{iid}_a.csv"
        if not gold_path.exists():
            cols, rows, err = run_gold(src, r["gold_sql"], a.timeout)
            if err:
                failures[err.split(":")[0]] += 1
                continue
            if not cols or len(rows) == 0 or len(rows) > a.max_rows:
                failures["empty or oversized"] += 1
                continue
            # The preview gate reads the RECORDED preview; it cannot see what the
            # query really returns. local_syn0139 passed it and produced a gold of
            # one all-blank row, which then scored every correct answer wrong.
            flat = [("" if v is None else str(v)).strip() for r_ in rows for v in r_]
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
        else:
            skipped += 1
        link = dbdir / f"{db_file}"
        if not link.exists():
            os.symlink(src, link)
        questions.append({"instance_id": iid, "db": db_file[:-7],
                          "question": r["question"], "external_knowledge": None})
        # synthetic questions rarely specify ordering; gold order is incidental
        standards.append({"instance_id": iid, "ignore_order": True,
                          "condition_cols": None})

    with open(lite / "spider2-lite.jsonl", "w") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")
    with open(lite / "evaluation_suite/gold/spider2lite_eval.jsonl", "w") as f:
        for s in standards:
            f.write(json.dumps(s) + "\n")

    print(f"\ngold written {made}, reused {skipped}, usable questions {len(questions)}")
    if failures:
        print("gold generation failures:")
        for k, v in failures.most_common():
            print(f"    {k:<28}{v}")
    print(f"\nroot ready: {a.root}")
    print(f"run with:  NL2SQL_DATA_ROOT={a.root} uv run python scripts/run_benchmark.py ...")


if __name__ == "__main__":
    main()
