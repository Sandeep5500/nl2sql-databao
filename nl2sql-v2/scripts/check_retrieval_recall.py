#!/usr/bin/env python3
"""Does the warehouse retrieval index actually find the right tables?

    uv run python scripts/check_retrieval_recall.py --source spider2_lite_bq

This is the gate that has to pass BEFORE spending GPU and scan budget on a retrieval
lane. The index is synthesised from the catalog rather than built by the DCE
pipeline, and the embedding prefixes have to match between build and query, so
"retrieval is wired up" and "retrieval works" are different claims.

The ground truth is the official gold SQL: spider2-lite ships it for 148 of the 204
BigQuery instances. Every backticked table in a question's gold query is a table the
answer genuinely needs, so recall@k over that set is a direct measurement, not a
proxy.

What the numbers mean:
  recall@8 per table     of all gold tables, how many were retrieved
  all-tables@8           questions where EVERY gold table was retrieved -- the one
                         that matters, since a join needs all of them
Below roughly 70% all-tables@8, suspect the index before suspecting the model; the
first thing to check is that the .npz query_prefix matches how it was built.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import DATA_SOURCES, GOLD_SQL_DIR
from nl2sql.context import CatalogSearchContext
from run_benchmark import load_questions, warehouse_index_dir

# backticked `project.dataset.table`, which is how the gold SQL writes every
# reference on BigQuery (the project ids are hyphenated, so backticks are required)
GOLD_REF = re.compile(r"`([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_$*\-]+)`")
# a date shard or any partial wildcard over one: _20170801, _201707*, _2017*, _*
SHARD_TAIL = re.compile(r"_[0-9]*\*?$")


def canon(name: str, families: set) -> str:
    """Fold a table name onto the collapsed family the index actually holds.

    Driven by the index's own families rather than a regex over every name, so
    genuinely separate tables that merely end in digits (census_2016 vs
    census_2017) are still compared literally.
    """
    if name in families:
        return name
    stem = SHARD_TAIL.sub("", name)
    cand = f"{stem}_*"
    return cand if cand in families else name


def gold_tables(iid: str) -> set:
    p = GOLD_SQL_DIR / f"{iid}.sql"
    if not p.exists():
        return set()
    sql = p.read_text(encoding="utf-8", errors="replace")
    return set(GOLD_REF.findall(sql))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="spider2_lite_bq")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("-k", type=int, default=8, help="tables retrieved per query")
    ap.add_argument("--verbose", action="store_true",
                    help="list the questions where retrieval missed")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the report here as well as printing it; defaults to "
                         "recall_report.json beside the index")
    args = ap.parse_args()

    src = DATA_SOURCES[args.source]
    idx = warehouse_index_dir(src.dialect)
    qs = load_questions([src])
    if args.limit:
        qs = qs[: args.limit]

    with_gold = [(q, gold_tables(q["instance_id"])) for q in qs]
    with_gold = [(q, g) for q, g in with_gold if g]
    print(f"{len(with_gold)}/{len(qs)} questions ship gold SQL with table refs")
    print(f"index: {idx}\n")

    caches, misses = {}, []
    n_tab = n_hit = n_all = 0
    no_index = Counter()
    for q, gold in with_gold:
        db = q["db"]
        if db not in caches:
            try:
                caches[db] = CatalogSearchContext(idx, db)
            except FileNotFoundError:
                caches[db] = None
        sc = caches[db]
        if sc is None:
            no_index[db] += 1
            continue
        fams = {t for t in sc.tables if t.endswith("_*")}
        top, _hops = sc.rank_tables(q["question"], limit=args.k)
        got = {canon(t, fams) for t, _s, _c in top}
        want = {canon(g, fams) for g in gold}
        hit = want & got
        n_tab += len(want)
        n_hit += len(hit)
        if hit == want:
            n_all += 1
        else:
            misses.append((q["instance_id"], db, sorted(want - hit), sorted(got)[:4]))

    scored = len(with_gold) - sum(no_index.values())
    if not scored:
        raise SystemExit("no question had an index to search; "
                         "run scripts/build_bq_context.py --all first")
    print(f"questions scored : {scored}")
    print(f"recall@{args.k} per table: {n_hit}/{n_tab} = "
          f"{100 * n_hit / max(n_tab, 1):.1f}%")
    print(f"all-tables@{args.k}      : {n_all}/{scored} = "
          f"{100 * n_all / scored:.1f}%   <- the one that matters")
    if no_index:
        print(f"\n{sum(no_index.values())} question(s) had no index, across "
              f"{len(no_index)} database(s): {', '.join(sorted(no_index))}")
    report = {
        "source": args.source, "k": args.k, "index": str(idx),
        "questions_with_gold": len(with_gold), "questions_scored": scored,
        "gold_tables": n_tab, "gold_tables_found": n_hit,
        "recall_per_table_pct": round(100.0 * n_hit / max(n_tab, 1), 1),
        "all_tables_questions": n_all,
        "all_tables_pct": round(100.0 * n_all / scored, 1),
        "no_index_questions": sum(no_index.values()),
        "no_index_databases": sorted(no_index),
        "misses": [{"instance": i, "db": d, "missed": m, "top": g}
                   for i, d, m, g in misses],
    }
    out = args.json or (idx / "recall_report.json")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"\nreport written to {out}")
    except OSError as e:
        print(f"\ncould not write the report to {out}: {e}")

    if misses:
        print(f"\n{len(misses)} question(s) missed at least one gold table")
        if args.verbose:
            for iid, db, missed, got in misses[:40]:
                print(f"  {iid} ({db})")
                print(f"     missed: {', '.join(m.rsplit('.', 1)[-1] for m in missed)}")
                print(f"     top   : {', '.join(g.rsplit('.', 1)[-1] for g in got)}")
        else:
            print("  pass --verbose to see them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
