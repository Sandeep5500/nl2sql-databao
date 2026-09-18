"""Shared plumbing for the analysis scripts: paths, question loading, run
discovery, and a cached re-score of every stored SQL with the current scorer.

Stored scores inside trace files go stale whenever eval.py changes (it changed
three times in Sept 2026), so every analysis re-executes the stored SQL. That
takes minutes, so results are cached in logs/analysis/, keyed by the SQL text,
and the cache discards itself if eval.py or db.py change.

A run spec is a directory name under logs/traces/, or a glob. A glob merges
directories into one logical run, so the shards of one arm ('arm_sweep_*')
are analysed as a single run.
"""

import glob
import hashlib
import json
import math
import os
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "src"))   # nl2sql-v2/src
sys.path.insert(0, str(HERE.parents[1]))           # nl2sql-v2/scripts
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from nl2sql.config import (EVAL_JSONL, GOLD_EXEC_DIR, GOLD_SQL_DIR,  # noqa: E402
                           QUESTIONS_FILE, REPO_ROOT, SQLITE_DIR)
from nl2sql.db import Database  # noqa: E402
from nl2sql.eval import load_eval_standards, score_against_gold  # noqa: E402

TRACES_DIR = REPO_ROOT / "logs" / "traces"
ANALYSIS_DIR = REPO_ROOT / "logs" / "analysis"
GREEDY = "v2_armAplus"
LANES = ["v2_pass4_k1", "v2_pass4_k2", "v2_pass4_k3", "v2_pass4_k4"]
PHASE0_RUNS = [GREEDY] + LANES


# ── questions and gold ────────────────────────────────────────────────────
def local_questions() -> dict:
    """instance_id -> question record, local split only."""
    out = {}
    with open(QUESTIONS_FILE) as f:
        for line in f:
            q = json.loads(line)
            if q["instance_id"].startswith("local"):
                out[q["instance_id"]] = q
    return out


def gold_files(iid: str) -> list[Path]:
    pat = re.compile(rf"^{re.escape(iid)}(_[a-z])?\.csv$")
    return sorted(GOLD_EXEC_DIR / f for f in os.listdir(GOLD_EXEC_DIR) if pat.match(f))


def gold_shape(iid: str) -> tuple[int, int]:
    """(rows, cols) of the smallest accepted gold answer — the most permissive."""
    shapes = []
    for f in gold_files(iid):
        try:
            shapes.append(pd.read_csv(f).shape)
        except Exception:
            pass
    return min(shapes) if shapes else (0, 0)


# ── runs and traces ───────────────────────────────────────────────────────
def load_traces(specs: list[str]) -> dict:
    """{run_spec: {instance_id: trace}} for every trace that submitted SQL.
    A question with no SQL in a run is simply absent, i.e. a failure."""
    out = {}
    for spec in specs:
        dirs = sorted(Path(p) for p in glob.glob(str(TRACES_DIR / spec)) if Path(p).is_dir())
        if not dirs:
            raise SystemExit(f"no trace directory matches {spec!r} under {TRACES_DIR}")
        merged = {}
        for d in dirs:
            for p in d.glob("local*.json"):
                t = json.loads(p.read_text())
                if t.get("sql"):
                    merged[p.stem] = t
        out[spec] = merged
    return out


def _sql_key(iid: str, sql: str) -> str:
    return f"{iid}:{hashlib.sha1(sql.encode()).hexdigest()[:16]}"


def _fingerprint() -> str:
    src = HERE.parents[2] / "src" / "nl2sql"
    h = hashlib.sha1()
    for name in ("eval.py", "db.py"):
        h.update((src / name).read_bytes())
    return h.hexdigest()[:12]


def rescore(traces: dict, qdb: dict) -> dict:
    """{(run_spec, instance_id): bool} — does the stored SQL score correct under
    the CURRENT scorer? Executes through the agent's own DuckDB path."""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS_DIR / "rescore_cache.json"
    fp = _fingerprint()
    cache = {}
    if path.exists():
        blob = json.loads(path.read_text())
        if blob.get("fingerprint") == fp:
            cache = blob["scores"]

    todo = defaultdict(list)
    for by_iid in traces.values():
        for iid, t in by_iid.items():
            key = _sql_key(iid, t["sql"])
            if key not in cache:
                todo[qdb[iid]].append((key, iid, t["sql"]))

    if todo:
        std = load_eval_standards()
        n = sum(len(v) for v in todo.values())
        print(f"re-scoring {n} stored queries (cached for next time) ...", file=sys.stderr)
        for db_name, items in sorted(todo.items()):
            p = SQLITE_DIR / f"{db_name}.sqlite"
            if not p.exists():
                cache.update({key: False for key, _, _ in items})
                continue
            db = Database(p)
            for key, iid, sql in items:
                try:
                    df, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
                    cache[key] = score_against_gold(df, iid, std)[0] == 1
                except Exception:
                    cache[key] = False
            db.close()
        path.write_text(json.dumps({"fingerprint": fp, "scores": cache}))

    return {(spec, iid): cache[_sql_key(iid, t["sql"])]
            for spec, by_iid in traces.items() for iid, t in by_iid.items()}


def passes_reliably(db_path, sql: str, iid: str, std: dict, repeats: int = 3) -> bool:
    """True only if the query scores correct on EVERY one of `repeats` fresh
    executions. Some queries are nondeterministic (e.g. LIMIT over tied rows,
    window functions without ORDER BY) and flip between runs -- local219's
    official gold SQL passes about 3 times in 20."""
    for _ in range(repeats):
        try:
            db = Database(db_path)
            df, _ = db.query_preview(sql, preview_rows=1, max_rows=5000)
            db.close()
            if score_against_gold(df, iid, std)[0] != 1:
                return False
        except Exception:
            return False
    return True


# ── buckets ───────────────────────────────────────────────────────────────
def buckets(qdb: dict) -> dict:
    """Fixed reference frame, always computed from the five Phase-0 runs so it
    stays stable when new arms are analysed against it.
      A  greedy solves it
      B  greedy fails, a sampled lane solves it
      C  no Phase-0 run has ever solved it"""
    ok = rescore(load_traces(PHASE0_RUNS), qdb)
    solved = defaultdict(set)
    for (spec, iid), good in ok.items():
        if good:
            solved[iid].add(spec)
    A = {i for i in qdb if GREEDY in solved[i]}
    B = {i for i in qdb if solved[i] and GREEDY not in solved[i]}
    C = set(qdb) - A - B
    return {"A": A, "B": B, "C": C, "lane_rate": {
        i: sum(1 for lane in LANES if lane in solved[i]) / len(LANES) for i in qdb}}


def chance_null(lane_rate: dict, ids) -> tuple[float, float]:
    """How many of `ids` a blind redraw wins with no help, and the 2-sigma bar
    an intervention must clear to count as a real effect."""
    p = [lane_rate[i] for i in ids]
    expected = sum(p)
    return expected, expected + 2 * math.sqrt(sum(x * (1 - x) for x in p))


# ── schema linkage ────────────────────────────────────────────────────────
def schema_of(db: Database) -> dict:
    """lowercased table -> set of lowercased real column names."""
    real = {}
    for t in db.list_tables():
        try:
            real[t.lower()] = {c.lower() for c, _, _ in db._columns(t)}
        except ValueError:
            pass
    return real


def linkage(sql: str, real: dict):
    """(tables, columns) a query touches, restricted to names that exist in the
    schema. sqlglot reports aliases such as `cnt` as columns; this drops them.
    Returns None if the query touches no real table."""
    from build_oracle_context import extract
    info = extract(sql)
    if not info:
        return None
    tables = frozenset(t.lower() for t in info["tables"] if t.lower() in real)
    if not tables:
        return None
    in_schema = set().union(*(real[t] for t in tables))
    return tables, frozenset(c.lower() for c in info["columns"] if c.lower() in in_schema)
