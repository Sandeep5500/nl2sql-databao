#!/usr/bin/env python3
"""Offline answer selection: pick one answer per question from several finished runs.

Pool: one candidate per (run, question), the query each run submitted (or the query its
step-cap fallback auto-submitted). Runs load from raw traces (logs/traces/<run>/) or
Inspect logs (logs/inspect/<run>.eval) through review/traces_lib.py.

Answer signatures come from the stored preview of the submitted query: parse the CSV,
round numeric cells to 2 decimals, sort the columns by their value multiset and sort the
rows (column names ignored). A complete preview (every row shown, no trimmed cell) is
the whole answer; a partial one keeps its total row count and visible rows.
Two agreement modes:
  exact      identical signatures
  tolerant   projection-tolerant: same row count, and every column of the narrower
             answer matches a distinct column of the wider one as a value multiset
             (a subset/superset of columns on shared values). This mirrors the scorer,
             which tolerates extra columns.

Selectors (each returns a distribution over candidates; ties are split uniformly, so
scores are exact expectations, not one random draw):
  greedy                         the --greedy-run candidate
  random                         uniform over candidates (expected pass@1)
  vote_exact[+submitted][+greedy_tiebreak]
  vote_tolerant[+submitted][+greedy_tiebreak]
                                 plurality vote; +submitted votes among submitted answers
                                 when any exist (fallback answers otherwise);
                                 +greedy_tiebreak lets the greedy answer win ties;
                                 tolerant ties prefer the widest answer
  lint+vote_tolerant+submitted   drop candidates whose submitted query a composite-key or
                                 fan-out detector flagged (--lint-flags), then vote
  oracle                         any correct candidate (upper bound, never chosen)

Labels (what "correct" means): official-parity score (nl2sql.eval, CSV round trip) of
the complete preview; for an incomplete preview the run's recorded score is used and
counted as such. --reexec (cluster, needs the SQLite DBs) re-executes every candidate's
SQL uncapped, and both signatures and labels come from the full result.

Reported per selector: expected total, 95% bootstrap CI over questions, the paired
difference to greedy with its CI, and a split-half hold-out: the best selector is chosen
on odd-numbered questions (local001, local003, ...) and scored on even ones, and vice
versa; the sum of the two held-out halves estimates "pick the best rule" honestly.

Usage (from nl2sql-v2/):
    uv run python scripts/select_answers.py                            # A+ and pass@4 k1..k4
    uv run python scripts/select_answers.py --with-draft \\
        --lint-flags ../logs/selection/flags --exclude-tasks scripts/gold_sensitive_tasks.yaml \\
        --out-csv ../results/selection_choices.csv --out-json ../results/selection.json
    # cluster (CPU node with the SQLite DBs): uncapped re-execution, cached
    uv run python scripts/select_answers.py --reexec --workers 4 \\
        --reexec-cache ../results/selection_reexec_cache.jsonl
Local (no DBs): NL2SQL_DATA_ROOT=<dir with Spider2/> uv run --no-project --with pandas \\
    --with duckdb --with sqlglot --with pyyaml --with inspect-ai python scripts/select_answers.py

Runs made with run_benchmark --hooks parse their previews without the hook notes and step
notices (raw traces only); runs made with --null-marker need the same --null-marker here.

Lint flag files are detector outputs named flags_P_<KIND>.csv with columns run,
instance_id, hit_submitted (run = run name or short label: A+, k1..k4, draft).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect as pyinspect
import io
import json
import math
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS / "src"))
sys.path.insert(0, str(HARNESS / "review"))
sys.path.insert(0, str(HARNESS / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import traces_lib as tl  # noqa: E402
from nl2sql import config  # noqa: E402
from nl2sql.eval import load_eval_standards, score_against_gold  # noqa: E402

try:  # shared with rescore_runs.py when present (preview decoding, re-execution)
    import rescore_runs as rr
except Exception:  # noqa: BLE001 - optional helper module
    rr = None

GREEDY = "v2_armAplus"
DEFAULT_RUNS = [GREEDY] + [f"v2_pass4_k{i}" for i in range(1, 5)]
DRAFT_RUN = "v2_draft_arctic"
SHORT_LABELS = {"v2_armAplus": "A+", "v2_draft_arctic": "draft", "v2_armC": "armC",
                "v2_oracle_supplement": "oracle_supp",
                **{f"v2_pass4_k{i}": f"k{i}" for i in range(1, 5)}}
DEFAULT_LINT_KINDS = ("COMPOSITE_KEY", "FANOUT")
_NUMERIC_RE = re.compile(r"^\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*$")
_SCORER_HAS_ROUNDTRIP = "roundtrip" in pyinspect.signature(score_against_gold).parameters


# ── answers ──────────────────────────────────────────────────────────────────
@dataclass
class Answer:
    sig: str                      # exact signature (hash)
    kind: str                     # complete | partial | unparseable
    total: int | None             # total rows of the full result
    ncols: int
    colvecs: list | None = None   # sorted normalized values per column
    ordered: list | None = None   # normalized values per column, preview order
    distinct: list | None = None  # distinct values per column


NULL_MARKER: str | None = None    # --null-marker: preview text of SQL NULL (read back as '')


def norm_cell(value: str) -> str:
    s = "" if value is None else str(value)
    if NULL_MARKER is not None and s == NULL_MARKER:
        return ""
    if _NUMERIC_RE.match(s):
        f = float(s)
        if math.isfinite(f):
            r = round(f, 2)
            return f"{0.0 if r == 0 else r:.2f}"
    return s.strip()


def parse_body(body: str) -> pd.DataFrame:
    if not body.strip():
        return pd.DataFrame()
    return pd.read_csv(io.StringIO(body), dtype=str, keep_default_na=False)


def make_answer(body: str | None, complete: bool, total: int | None) -> Answer:
    body = body or ""
    try:
        df = parse_body(body)
    except Exception:  # noqa: BLE001 - e.g. a preview cut at 16K chars mid-row
        digest = hashlib.sha1(("raw:" + body).encode()).hexdigest()[:16]
        return Answer(sig=f"u:{digest}", kind="unparseable", total=total, ncols=0)
    cols = [[norm_cell(v) for v in df.iloc[:, j].tolist()] for j in range(df.shape[1])]
    order = sorted(range(len(cols)), key=lambda j: sorted(cols[j]))
    rows = sorted(zip(*[cols[j] for j in order])) if cols else []
    shown = len(df)
    total = shown if (complete or total is None) else total
    kind = "complete" if complete else "partial"
    payload = repr((kind, total if kind == "partial" else None, len(cols), rows))
    digest = hashlib.sha1(payload.encode()).hexdigest()[:16]
    return Answer(sig=f"{kind[0]}:{digest}", kind=kind, total=total, ncols=len(cols),
                  colvecs=[tuple(sorted(c)) for c in cols], ordered=[tuple(c) for c in cols],
                  distinct=[len(set(c)) for c in cols])


def _sub_multiset(small, big) -> bool:
    cs, cb = Counter(small), Counter(big)
    return all(cb[v] >= n for v, n in cs.items())


def _col_ok(a: Answer, j: int, b: Answer, k: int) -> bool:
    ap, bp = a.kind == "partial", b.kind == "partial"
    if not ap and not bp:
        return a.colvecs[j] == b.colvecs[k]
    if ap and bp:  # both show the first rows of their own order
        m = min(len(a.ordered[j]), len(b.ordered[k]))
        return sorted(a.ordered[j][:m]) == sorted(b.ordered[k][:m])
    return (_sub_multiset(a.colvecs[j], b.colvecs[k]) if ap
            else _sub_multiset(b.colvecs[k], a.colvecs[j]))


def compatible(a: Answer, b: Answer) -> bool:
    """Projection-tolerant agreement (see module docstring)."""
    if a.sig == b.sig:
        return True
    if a.colvecs is None or b.colvecs is None or a.total != b.total:
        return False
    if a.total == 0:
        return True
    narrow, wide = (a, b) if a.ncols <= b.ncols else (b, a)
    if narrow.ncols == 0:
        return False
    match: dict[int, int] = {}          # wide column -> narrow column

    def augment(j: int, seen: set) -> bool:
        for k in range(wide.ncols):
            if k in seen or not _col_ok(narrow, j, wide, k):
                continue
            seen.add(k)
            if k not in match or augment(match[k], seen):
                match[k] = j
                return True
        return False

    if not all(augment(j, set()) for j in range(narrow.ncols)):
        return False
    # constant columns alone (e.g. a column of 1s) are not evidence of agreement
    return (narrow.total or 0) <= 1 or any(d > 1 for d in narrow.distinct)


# ── candidates ───────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    run: str
    iid: str
    db: str | None
    status: str                   # submitted | fallback
    query_id: str | None
    sql: str | None
    setup: list
    steps: int | None
    recorded: int
    preview: dict
    answer: Answer | None = None
    label: int = 0
    label_source: str = ""        # parity | recorded | reexec | reexec_error:...
    flagged: bool = False
    extra: dict = field(default_factory=dict)


def _setup_statements(events: list[dict], upto: int | None) -> list[str]:
    if rr is not None and hasattr(rr, "_setup_statements"):
        return rr._setup_statements(events, upto)
    setup = []
    for ev in events[:upto]:
        if ev.get("kind") == "tool" and ev.get("name") in tl.SQL_TOOLS \
                and ev.get("error") is None \
                and tl._SET_ALL_VARCHAR_RE.search((ev.get("args") or {}).get("sql") or ""):
            setup = ["SET sqlite_all_varchar=true"]
    return setup


def load_run(run: str, logs_dir: Path, discovered: dict) -> list[dict]:
    found = discovered.get(run)
    if not found:
        raise SystemExit(f"run {run!r} not found under {logs_dir}/traces or {logs_dir}/inspect")
    if found["trace_dir"]:
        episodes = []
        for p in sorted(found["trace_dir"].glob("*.json")):
            ep = tl.load_trace_episode(p)
            if rr is not None and hasattr(rr, "harness_results"):
                # runs with --hooks: parse previews without notes and step notices
                trace = json.loads(p.read_text()).get("trace") or []
                clean = rr.harness_results(trace)
                if any(a is not b for a, b in zip(trace, clean)):
                    ep["events"] = tl.events_from_trace(clean)
                    tl.apply_declared_types(ep)
            episodes.append(ep)
        return episodes
    return tl.load_inspect_run(found["inspect"])


def load_candidates(runs: list[str], logs_dir: Path, keep) -> tuple[dict, dict]:
    """-> ({iid: {run: Candidate}}, {run: episode count})"""
    pool: dict = defaultdict(dict)
    counts = {}
    discovered = tl.discover_runs(logs_dir)
    for run in runs:
        episodes = [ep for ep in load_run(run, logs_dir, discovered) if keep(ep["instance_id"])]
        counts[run] = len(episodes)
        for ep in episodes:
            sub = tl.find_submitted(ep["events"], ep["status"])
            if not sub:
                continue
            ev = ep["events"][sub["event_idx"]]
            meta = tl.parse_sql_result(ev["result"])["result_meta"] or {}
            if rr is not None and hasattr(rr, "_preview_of"):
                # also reads run_benchmark --show-row-count's '[N rows]' marker
                pv = rr._preview_of(ep["events"], sub)
                sub = {**sub, "csv": pv.get("csv")}
                meta = {k: v for k, v in pv.items() if k not in ("query_id", "csv")}
            pool[ep["instance_id"]][run] = Candidate(
                run=run, iid=ep["instance_id"], db=ep.get("db"), status=ep["status"],
                query_id=sub["query_id"], sql=sub.get("sql"),
                setup=_setup_statements(ep["events"], sub["event_idx"]),
                steps=ep.get("steps"), recorded=int(ep.get("score") or 0),
                preview={"csv": sub.get("csv"), **meta})
    return pool, counts


# ── labels ───────────────────────────────────────────────────────────────────
def _preview_frame(body: str) -> pd.DataFrame:
    if rr is not None and hasattr(rr, "preview_frame"):
        return rr.preview_frame(body, NULL_MARKER)   # also decodes bytearray(b'...') cells
    df = pd.read_csv(io.StringIO(body), dtype=str, keep_default_na=False)
    return df if NULL_MARKER is None else df.replace(NULL_MARKER, "")


def parity_score(df: pd.DataFrame, iid: str, standards: dict, gold_dir=None) -> int:
    if _SCORER_HAS_ROUNDTRIP:
        kw = {"gold_dir": gold_dir} if gold_dir is not None else {}
        return score_against_gold(df, iid, standards, roundtrip=True, **kw)[0]
    rt = pd.read_csv(io.StringIO(df.to_csv(index=False))) if df.shape[1] else df
    return score_against_gold(rt, iid, standards)[0]


def label_from_preview(c: Candidate, standards: dict, mode: str, gold_dir=None) -> None:
    pv = c.preview
    c.answer = make_answer(pv.get("csv"), bool(pv.get("complete")), pv.get("total_rows"))
    if mode == "parity" and pv.get("complete"):
        try:
            c.label, c.label_source = parity_score(_preview_frame(pv.get("csv") or ""),
                                                   c.iid, standards, gold_dir), "parity"
            return
        except Exception:  # noqa: BLE001 - unparseable preview: keep the recorded score
            pass
    c.label, c.label_source = c.recorded, "recorded"


# ── re-execution (cluster) ───────────────────────────────────────────────────
def _execute(engine: str, db_path: Path, sql: str, setup: list, timeout: float,
             max_rows: int) -> tuple[pd.DataFrame, bool]:
    if rr is not None and engine == "sqlite" and hasattr(rr, "execute_sqlite"):
        return rr.execute_sqlite(db_path, sql, timeout, max_rows)
    if rr is not None and engine == "duckdb" and hasattr(rr, "execute_duckdb"):
        return rr.execute_duckdb(db_path, sql, setup, timeout, max_rows)
    if engine != "duckdb":
        raise RuntimeError("--engine sqlite needs scripts/rescore_runs.py")
    from nl2sql.db import Database
    db = Database(db_path)
    timer = threading.Timer(timeout, db.con.interrupt)
    timer.start()
    try:
        db.con.execute("SET threads=1")
        for stmt in setup:
            db.con.execute(stmt)
        df = db.con.execute(sql).df()
        return df.head(max_rows), len(df) > max_rows
    finally:
        timer.cancel()
        db.close()


def _frame_to_csv(df: pd.DataFrame) -> str:
    try:
        from nl2sql.eval import decode_bytes_cells
        df = decode_bytes_cells(df)
    except ImportError:
        pass
    return df.to_csv(index=False)


class Reexecutor:
    """Re-run each candidate's SQL uncapped; cache (answer, label) per (db, setup, sql)."""

    def __init__(self, args, standards: dict, gold_dir=None):
        self.args, self.standards, self.gold_dir = args, standards, gold_dir
        self.path = Path(args.reexec_cache) if args.reexec_cache else None
        self.cache: dict = {}
        self.lock = threading.Lock()
        if self.path and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec

    def key(self, c: Candidate) -> str:
        raw = json.dumps([c.iid, c.db, self.args.engine, c.setup, c.sql,
                          self.args.gold_dir or ""])
        return hashlib.sha1(raw.encode()).hexdigest()

    def run(self, c: Candidate) -> None:
        k = self.key(c)
        rec = self.cache.get(k)
        if rec is None:
            rec = {"key": k, "run": c.run, "iid": c.iid}
            db_path = config.SQLITE_DIR / f"{c.db}.sqlite"
            try:
                if not c.sql:
                    raise RuntimeError("no SQL")
                if not db_path.exists():
                    raise FileNotFoundError(f"{db_path}")
                df, over = _execute(self.args.engine, db_path, c.sql, c.setup,
                                    self.args.timeout, self.args.max_rows)
                rec.update(csv=_frame_to_csv(df), rows=len(df), over=over,
                           label=parity_score(df, c.iid, self.standards, self.gold_dir))
            except Exception as e:  # noqa: BLE001 - recorded per candidate
                rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            with self.lock:
                self.cache[k] = rec
                if self.path:
                    small = {kk: v for kk, v in rec.items() if kk != "csv"}
                    if "csv" in rec and len(rec["csv"]) <= self.args.cache_csv_chars:
                        small["csv"] = rec["csv"]
                    with open(self.path, "a") as f:
                        f.write(json.dumps(small) + "\n")
        if "error" in rec or "label" not in rec:
            c.label_source = f"reexec_error:{rec.get('error', 'uncached result')}"
            return                                     # keep the preview answer/label
        if "csv" in rec:
            c.answer = make_answer(rec["csv"], True, rec.get("rows"))
        c.label, c.label_source = int(rec["label"]), "reexec"
        c.extra["reexec_rows"] = rec.get("rows")


# ── lint flags ───────────────────────────────────────────────────────────────
def load_lint_flags(paths: list[str], kinds) -> tuple[set, list]:
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        files += sorted(p.glob("flags_*.csv")) if p.is_dir() else [p]
    wanted = {k.upper() for k in kinds}
    flagged, used = set(), []
    for f in files:
        kind = re.sub(r"^flags_(P_)?", "", f.stem).upper()
        if kind not in wanted or not f.exists():
            continue
        used.append(f.name)
        for row in csv.DictReader(open(f, newline="")):
            if str(row.get("hit_submitted", "")).strip() in ("1", "1.0", "True", "true"):
                flagged.add((row["run"], row["instance_id"]))
    return flagged, used


# ── selectors ────────────────────────────────────────────────────────────────
def uniform(cands: list[Candidate]) -> dict:
    return {c.run: Fraction(1, len(cands)) for c in cands} if cands else {}


def only_submitted(cands: list[Candidate]) -> list[Candidate]:
    return [c for c in cands if c.status == "submitted"] or cands


def vote_exact(cands: list[Candidate], greedy: str | None = None) -> dict:
    if not cands:
        return {}
    clusters: dict = defaultdict(list)
    for c in cands:
        clusters[c.answer.sig].append(c)
    best = max(len(v) for v in clusters.values())
    top = [v for v in clusters.values() if len(v) == best]
    if greedy and len(top) > 1:
        top = [v for v in top if any(c.run == greedy for c in v)] or top
    out: dict = {}
    for members in top:
        for c in members:
            out[c.run] = out.get(c.run, 0) + Fraction(1, len(top) * len(members))
    return out


def vote_tolerant(cands: list[Candidate], greedy: str | None = None) -> dict:
    if not cands:
        return {}
    support = {c.run: sum(compatible(c.answer, o.answer) for o in cands) for c in cands}
    best = max(support.values())
    top = [c for c in cands if support[c.run] == best]
    if greedy and any(c.run == greedy for c in top):
        return {greedy: Fraction(1)}
    widest = max(c.answer.ncols for c in top)
    return uniform([c for c in top if c.answer.ncols == widest])


def _pick(run: str | None):
    return lambda cands: ({run: Fraction(1)} if any(c.run == run for c in cands) else {})


def build_selectors(greedy: str | None, lint: bool) -> dict:
    sel = {}
    if greedy:
        sel["greedy"] = _pick(greedy)
    sel.update({
        "random": uniform,
        "vote_exact": vote_exact,
        "vote_exact+submitted": lambda cs: vote_exact(only_submitted(cs)),
        "vote_tolerant": vote_tolerant,
        "vote_tolerant+submitted": lambda cs: vote_tolerant(only_submitted(cs)),
    })
    if greedy:
        sel["vote_exact+greedy_tiebreak"] = lambda cs: vote_exact(cs, greedy)
        sel["vote_tolerant+submitted+greedy_tiebreak"] = \
            lambda cs: vote_tolerant(only_submitted(cs), greedy)
    if lint:
        sel["lint+vote_tolerant+submitted"] = \
            lambda cs: vote_tolerant(only_submitted([c for c in cs if not c.flagged] or cs))
    return sel


# ── evaluation ───────────────────────────────────────────────────────────────
def expected(dist: dict, by_run: dict) -> Fraction:
    return sum((p * by_run[r].label for r, p in dist.items()), Fraction(0))


def iid_number(iid: str) -> int:
    m = re.search(r"(\d+)$", iid)
    return int(m.group(1)) if m else 0


def bootstrap(mat: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """mat: (selectors, questions) -> (selectors, n_boot) resampled totals."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, mat.shape[1], size=(n_boot, mat.shape[1]))
    return mat[:, idx].sum(axis=2)


def split_half(mat: np.ndarray, names: list[str], iids: list[str]) -> dict:
    odd = np.array([iid_number(i) % 2 == 1 for i in iids])
    choosable = [j for j, n in enumerate(names) if n != "oracle"]
    halves = {}
    for label, train in (("odd->even", odd), ("even->odd", ~odd)):
        test = ~train
        best = max(choosable, key=lambda j: (mat[j, train].sum(), -j))
        halves[label] = {"chosen": names[best], "train_total": float(mat[best, train].sum()),
                         "test_total": float(mat[best, test].sum()),
                         "n_train": int(train.sum()), "n_test": int(test.sum())}
    return {"halves": halves,
            "held_out_total": sum(h["test_total"] for h in halves.values())}


def read_ids(value: str | None) -> set[str] | None:
    """Ids from a comma list, a text/CSV file, or a yaml file with an `ids` list."""
    if not value:
        return None
    p = Path(value)
    if not p.is_file():
        return {t for t in re.split(r"[\s,]+", value) if t}
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(text)
        if isinstance(data, dict) and isinstance(data.get("ids"), list):
            return {str(i) for i in data["ids"]}
    rows = list(csv.reader(io.StringIO(text)))
    if rows and "instance_id" in rows[0]:
        j = rows[0].index("instance_id")
        return {r[j] for r in rows[1:] if len(r) > j and r[j]}
    text = re.sub(r"#[^\n]*", "", text)
    return {t for t in re.split(r"[\s,]+", text) if re.match(r"^local\d+$", t)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", help=f"comma-separated runs (default: {','.join(DEFAULT_RUNS)})")
    ap.add_argument("--with-draft", action="store_true", help=f"add {DRAFT_RUN} to the pool")
    ap.add_argument("--greedy-run", default=GREEDY,
                    help="run used by greedy / greedy_tiebreak ('' disables them)")
    ap.add_argument("--logs", type=Path, default=tl.LOGS_DIR)
    ap.add_argument("--labels", choices=["parity", "recorded"], default="parity",
                    help="parity: official-parity score of complete previews (recorded "
                         "score otherwise); recorded: the runs' own scores")
    ap.add_argument("--lint-flags", action="append", default=[],
                    help="flag CSV file or directory of flags_*.csv (repeatable)")
    ap.add_argument("--lint-kinds", default=",".join(DEFAULT_LINT_KINDS))
    ap.add_argument("--task-list", help="ids to keep (comma list or file)")
    ap.add_argument("--exclude-tasks", help="ids to drop (comma list, file, or yaml with ids)")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-csv", help="per (selector, question) choices")
    ap.add_argument("--out-json", help="summary json")
    ap.add_argument("--reexec", action="store_true",
                    help="re-execute candidate SQL uncapped (needs the SQLite DBs)")
    ap.add_argument("--engine", choices=["duckdb", "sqlite"], default="duckdb")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--max-rows", type=int, default=1_000_000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--reexec-cache", help="jsonl cache of re-execution results (resumable)")
    ap.add_argument("--cache-csv-chars", type=int, default=2_000_000,
                    help="store result CSVs up to this size in the cache")
    ap.add_argument("--gold-dir", help="alternate gold/ or exec_result/ directory "
                                       "(needs scripts/rescore_runs.py)")
    ap.add_argument("--null-marker", help="runs made with run_benchmark --null-marker: this "
                                          "preview text is SQL NULL (read as empty)")
    args = ap.parse_args(argv)
    global NULL_MARKER
    NULL_MARKER = args.null_marker

    runs = [r.strip() for r in args.runs.split(",")] if args.runs else list(DEFAULT_RUNS)
    if args.with_draft and DRAFT_RUN not in runs:
        runs.append(DRAFT_RUN)
    greedy = args.greedy_run if args.greedy_run in runs else None
    if args.greedy_run and not greedy:
        print(f"[note: greedy run {args.greedy_run} is not in the pool; greedy selectors off]")
    keep_ids, drop_ids = read_ids(args.task_list), read_ids(args.exclude_tasks) or set()
    keep = lambda i: (keep_ids is None or i in keep_ids) and i not in drop_ids  # noqa: E731

    gold_dir, standards = None, None
    if args.gold_dir:
        if rr is None:
            raise SystemExit("--gold-dir needs scripts/rescore_runs.py")
        gold_dir, standards = rr.resolve_gold(args.gold_dir)
    standards = standards or load_eval_standards()

    pool, counts = load_candidates(runs, args.logs, keep)
    universe = sorted({i for i in tl.load_questions() if keep(i)} | set(pool))
    for iid in universe:
        for c in pool.get(iid, {}).values():
            label_from_preview(c, standards, args.labels, gold_dir)

    if args.reexec:
        rex = Reexecutor(args, standards, gold_dir)
        todo = [c for iid in universe for c in pool.get(iid, {}).values()]
        print(f"re-executing {len(todo)} candidates ({len(rex.cache)} cached) "
              f"with {args.workers} worker(s)")
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            list(ex.map(rex.run, todo))

    flagged, flag_files = set(), []
    if args.lint_flags:
        flagged, flag_files = load_lint_flags(args.lint_flags, args.lint_kinds.split(","))
        for iid in universe:
            for c in pool.get(iid, {}).values():
                c.flagged = ((SHORT_LABELS.get(c.run, c.run), iid) in flagged
                             or (c.run, iid) in flagged)
        if not flag_files:
            print(f"[warn: no flags_*.csv of kinds {args.lint_kinds} in {args.lint_flags}]")

    selectors = build_selectors(greedy, bool(flag_files))
    names = list(selectors) + ["oracle"]
    mat = np.zeros((len(names), len(universe)))
    choice_rows = []
    for q, iid in enumerate(universe):
        by_run = pool.get(iid, {})
        cands = [by_run[r] for r in runs if r in by_run]
        for s, name in enumerate(names):
            if name == "oracle":
                dist = {c.run: Fraction(1) for c in cands if c.label}
                val = Fraction(1) if dist else Fraction(0)
            else:
                dist = selectors[name](cands)
                val = expected(dist, by_run)
            mat[s, q] = float(val)
            choice_rows.append({
                "selector": name, "instance_id": iid, "expected_score": f"{float(val):.4f}",
                "chosen": ";".join(f"{r}:{float(p):.3f}" for r, p in sorted(dist.items())),
                "n_candidates": len(cands),
                "labels": ";".join(f"{c.run}={c.label}{'' if c.label_source == 'parity' else '(' + c.label_source.split(':')[0] + ')'}"
                                   for c in cands)})

    # ── report ──
    n = len(universe)
    print(f"\npool: {', '.join(runs)} | questions: {n}"
          + (f" (excluded {len(drop_ids)})" if drop_ids else "")
          + f" | labels: {'reexec' if args.reexec else args.labels}")
    src = Counter(c.label_source.split(":")[0] for d in pool.values() for c in d.values())
    print("label sources:", dict(src))
    print(f"{'run':24} {'episodes':>8} {'answers':>8} {'complete':>8} {'recorded':>8} {'label':>6}")
    for r in runs:
        cs = [pool[i][r] for i in universe if r in pool.get(i, {})]
        print(f"{r:24} {counts.get(r, 0):>8} {len(cs):>8} "
              f"{sum(c.answer.kind == 'complete' for c in cs):>8} "
              f"{sum(c.recorded for c in cs):>8} {sum(c.label for c in cs):>6}")
    if flag_files:
        print(f"lint flags: {len(flagged)} flagged submissions from {', '.join(flag_files)}; "
              f"{sum(c.flagged for d in pool.values() for c in d.values())} in this pool")

    boots = bootstrap(mat, args.bootstrap, args.seed) if args.bootstrap else None
    g = names.index("greedy") if "greedy" in names else None
    summary = {"runs": runs, "n_questions": n, "labels": "reexec" if args.reexec else args.labels,
               "label_sources": dict(src), "selectors": {}}
    print(f"\n{'selector':42} {'expected':>8} {'95% CI':>15} {'vs greedy':>9} {'95% CI':>15}")
    for s, name in enumerate(names):
        tot = mat[s].sum()
        row = {"expected_total": round(float(tot), 3), "rate": round(float(tot) / max(n, 1), 4)}
        ci = dci = ""
        if boots is not None:
            lo, hi = np.percentile(boots[s], [2.5, 97.5])
            row["ci95"] = [round(float(lo), 2), round(float(hi), 2)]
            ci = f"[{lo:6.1f},{hi:6.1f}]"
        delta = ""
        if g is not None:
            d = tot - mat[g].sum()
            row["delta_vs_greedy"] = round(float(d), 3)
            delta = f"{d:+9.2f}"
            if boots is not None and s != g:
                dlo, dhi = np.percentile(boots[s] - boots[g], [2.5, 97.5])
                row["delta_ci95"] = [round(float(dlo), 2), round(float(dhi), 2)]
                dci = f"[{dlo:+6.1f},{dhi:+6.1f}]"
        summary["selectors"][name] = row
        print(f"{name:42} {tot:8.2f} {ci:>15} {delta:>9} {dci:>15}")
    sh = split_half(mat, names, universe)
    summary["split_half"] = sh
    print("\nsplit-half hold-out (choose the best selector on one half, score it on the other):")
    for label, h in sh["halves"].items():
        print(f"  {label}: chose {h['chosen']} (train {h['train_total']:.2f}/{h['n_train']}) "
              f"-> test {h['test_total']:.2f}/{h['n_test']}")
    best_in_sample = max((mat[j].sum(), nm) for j, nm in enumerate(names) if nm != "oracle")
    print(f"  held-out total {sh['held_out_total']:.2f}/{n} vs best in-sample "
          f"{best_in_sample[0]:.2f} ({best_in_sample[1]})"
          + (f", greedy {mat[g].sum():.2f}" if g is not None else ""))
    print("Expected totals split ties uniformly; labels on incomplete previews are the "
          "runs' recorded scores (use --reexec on the cluster for full results).")

    if args.out_csv:
        Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(choice_rows[0]) if choice_rows
                               else ["selector", "instance_id"])
            w.writeheader()
            w.writerows(choice_rows)
        print(f"choices -> {args.out_csv}")
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(summary, indent=2))
        print(f"summary -> {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
