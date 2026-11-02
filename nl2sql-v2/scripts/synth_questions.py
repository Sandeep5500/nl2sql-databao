#!/usr/bin/env python3
"""Synthesize (gold SQL, question) training items over a foreign database.

See documents/judge_finetuning_plan.md §3.2. Three stages per item:

  A. write gold SQL from the schema + a failure-mode template   (strong model)
  B. phrase a question for that SQL                             (strong model)
  C. gate: state the expected output shape, BLIND to the gold   (different model)

Gold correctness is free: we execute the SQL, so whatever it returns IS the gold.
What can be wrong is the question<->SQL correspondence, which stage C catches --
an independent reading of the question must agree with the gold's actual shape.
Stage C deliberately does NOT ask the validator to solve the question: a weaker
validator would then reject hard-but-well-posed items, which are the valuable
ones.

Usage (from nl2sql-v2/):
    # strong model for A+B, local vLLM for the gate
    OPENAI_API_KEY=sk-... uv run python scripts/synth_questions.py \\
        --db /tmp/bikeshare.sqlite --n 10 --out ../data/synth/pilot.jsonl \\
        --model gpt-5.4 \\
        --gate-base-url http://babel-x-y:8765/v1 --gate-model Qwen/Qwen3.5-9B

    # everything on one local endpoint (plumbing check only -- question quality
    # from a 9B is not representative)
    uv run python scripts/synth_questions.py --db /tmp/bikeshare.sqlite --n 10 \\
        --out ../data/synth/smoke.jsonl --base-url http://localhost:8765/v1
"""

import argparse
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import random
import re
import sqlite3
import zlib
import sys
from pathlib import Path

from openai import OpenAI

# ── failure-mode templates ────────────────────────────────────────────────
# Stratified from the measured taxonomy (plan §3.2). Each bucket teaches the
# judge a different discrimination; counts are lane-failures on the 135.

def stable_hash(s: str) -> int:
    """A process-independent digest.

    str.__hash__ is salted per interpreter (PYTHONHASHSEED), so seeding an RNG
    from hash() silently made --seed non-reproducible: the same seed produced a
    different combination order on every run, which also meant --resume did not
    reproduce the plan it was resuming.
    """
    return zlib.crc32(s.encode())


TEMPLATES = {
    "multi_clause": (
        "Compose THREE stages that must happen in order: first restrict to a set of "
        "entities by a computed condition, then rank or aggregate within that set, "
        "then compute a final figure over the survivors. The stages must not be "
        "reorderable without changing the answer."),
    "set_then_aggregate": (
        "Name a SET of entities by some criterion, then return ONE row: a single "
        "aggregate over that set. The set is a filter, not the output grain, so "
        "the result must be exactly 1 row."),
    "enumerated_columns": (
        "Return one row per entity with FIVE OR MORE distinct computed measures as "
        "separate columns, each a different kind of quantity (a count, a ratio, an "
        "average, an extreme, a label)."),
    "boundary": (
        "The answer must hinge on an edge that ORDINARY LANGUAGE settles but a "
        "careless query gets wrong silently. Use only this kind: a set quantified "
        "universally -- 'for each X' / 'every X' / 'all X' -- where some members "
        "have ZERO matching rows and must still appear (with a 0 or a NULL-safe "
        "value), so an inner join silently drops them; or a grouping key that is "
        "NULL for some rows, where the natural reading settles whether that group "
        "belongs. Do NOT use a tie at a cutoff: 'the top 5 when 5th and 6th tie' "
        "is genuinely ambiguous, so the question would have to state the rule and "
        "the trap would evaporate. You will also be asked for the naive query, and "
        "the item is discarded unless the two give different results."),
    "fanout": (
        "Join a one-to-many relationship where a naive join would multiply rows, so "
        "that the correct answer requires aggregating or de-duplicating before "
        "joining. The row count must differ from the naive version."),
    "metric_definition": (
        "Define a ratio or rate whose denominator is easy to get wrong -- exclude "
        "specific rows from the denominator but not the numerator, or vice versa. "
        "Same row count either way; only the values differ."),
}

# Measured against Spider 2.0's own gold SQL (232 non-local + 24 local files):
# median 105-123 words, 2-3 CTEs, 2-3 aggregates, 0 CASE, 0 window functions.
# Buckets that stayed at or below that scored 67-100% per-candidate accuracy;
# buckets above it scored 0-8% and produced NO usable training pairs:
#   enumerated_columns 177 words / 10 aggs / 3 CASE -> 0%
#   metric_definition  136 words /  4 aggs / 2 CASE -> 0%
#   multi_clause       128 words /  5 aggs / 5 subq -> 8%
# So the budget is stated explicitly rather than left to the model.
BUDGET = ("Complexity budget, matched to this benchmark's own gold queries: aim "
          "for about {words} words, {aggs} aggregate calls, at most {case} CASE "
          "expression(s) and {win} window function(s). Real gold queries in this "
          "benchmark use a median of 2-3 aggregates and NO CASE and NO window "
          "functions -- do not exceed the budget to look sophisticated. A query "
          "nobody can reproduce teaches nothing.")

# A share of items targets the shape of what we CANNOT solve. Measured over all
# 42 never-solved vs 49 always-solved questions (gold result CSVs exist for all
# 135, so this is the whole set, not a subsample):
#     results with >=5 columns   26% never-solved   vs  12% always-solved
#     question length            56 words           vs  36 words
# NOT aggregate count: that looked like 5.0 vs 2.0, but gold SQL exists for only
# 24 of the 135 locals, so it rested on 7 never-solved queries whose range
# ([1,3,4,5,6,7,8]) overlaps the always-solved range ([0,0,1,2,2,2,2,4,5,6]).
# Retracted rather than built on.
HARD_BUDGETS = {
    b: dict(words=170, aggs=6, case=1, win=1)
    for b in ("multi_clause", "set_then_aggregate", "enumerated_columns",
              "boundary", "fanout", "metric_definition")
}
HARD_NOTE = ("This item targets the HARD end of the distribution. The answer must "
             "have AT LEAST 5 output columns, and the question will be long "
             "(55+ words) because it has that many things to name. Questions of "
             "this shape are the ones the benchmark's hardest instances look "
             "like -- do not simplify toward the median.")

BUDGETS = {
    "multi_clause":       dict(words=120, aggs=3, case=1, win=1),
    "set_then_aggregate": dict(words=95,  aggs=3, case=0, win=0),
    "enumerated_columns": dict(words=130, aggs=4, case=1, win=0),
    "boundary":           dict(words=110, aggs=3, case=1, win=0),
    "fanout":             dict(words=110, aggs=3, case=0, win=0),
    "metric_definition":  dict(words=115, aggs=3, case=1, win=0),
}

# Forced variety on the headline measure, so items do not all collapse into
# "count of rows per entity". At n=10 without this, two of six buckets produced
# near-identical station/trip-count queries.
MEASURES = [
    "a count of events per entity",
    "a ratio or percentage with a carefully scoped denominator",
    "an average or median of a per-row quantity",
    "a maximum or minimum, with the row that attains it",
    "a span of time between two timestamps",
    "a share of a total, computed against a window or subtotal",
    "a change or difference between two periods",
    "a per-unit rate (per day, per member, per km)",
    "a label assigned by thresholds on a computed quantity",
    "a running or cumulative total over an ordering",
]


def load_hard_sql_exemplars(gold_dir: Path, limit: int = 60) -> list[str]:
    """Gold SQL from the hard end, for the targeted share of items.

    114 of the 232 non-local gold queries carry >=5 aggregates or >=4
    subqueries; their median is 156 words against 80 in the ordinary pool, which
    filters those out. Non-local only, so no test question or test gold SQL is
    involved -- same authors and benchmark, different databases.
    """
    out = []
    if not gold_dir.exists():
        return out
    for f in sorted(gold_dir.glob("*.sql")):
        if f.stem.startswith("local"):
            continue                      # our test set
        s = " ".join(f.read_text().split())
        aggs = len(re.findall(r"\b(sum|avg|count|min|max)\s*\(", s, re.I))
        subs = len(re.findall(r"\(\s*select\b", s, re.I))
        if (aggs >= 5 or subs >= 4) and len(s.split()) <= 400:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def load_sql_exemplars(gold_dir: Path, limit: int = 120) -> list[str]:
    """Real gold SQL from this benchmark, for stage A.

    Stage B got question exemplars and mechanism tells went from 6/10 to 0/30.
    Stage A had no benchmark input at all, so its complexity came only from my
    templates -- and three buckets overshot Spider 2.0 badly enough to yield no
    training pairs. Same remedy, applied to the query rather than the prose.

    LEAKAGE GUARD: local* files are the 24 gold queries for our test set and are
    excluded unconditionally.
    """
    out = []
    if not gold_dir.exists():
        return out
    for f in sorted(gold_dir.glob("*.sql")):
        if f.stem.startswith("local"):
            continue                      # our test set
        s = " ".join(f.read_text().split())
        if 40 <= len(s.split()) <= 180:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def load_exemplars(path: Path) -> list[str]:
    """Real questions from this benchmark family, for style only.

    LEAKAGE GUARD: the 135 `local*` instances are our test set and are excluded
    unconditionally. The ~412 non-local spider2-lite instances are different
    databases written by the same authors, so they carry the house style without
    touching the test set. Measured: non-local questions run a median of 50 words
    and 2 sentences, against 46 and 2 for the locals.
    """
    out = []
    with open(path) as f:
        for line in f:
            q = json.loads(line)
            iid = q.get("instance_id", "")
            if iid.startswith("local"):
                continue                      # our test set -- never an exemplar
            text = " ".join((q.get("question") or "").split())
            # Narrower than the full range: preferring long exemplars pushed
            # generated questions to a 94-word median against the benchmark's 50.
            if 30 <= len(text.split()) <= 75:
                out.append(text)
    return out


SEQUENCED = re.compile(r"\b(first|then|among|after that|next|finally)\b", re.I)


def pick_exemplars(pool: list[str], bucket: str, rng, k: int = 3) -> str:
    """Prefer exemplars whose shape matches the bucket we are generating."""
    if bucket in ("multi_clause", "set_then_aggregate"):
        cand = [q for q in pool if SEQUENCED.search(q)] or pool
    elif bucket == "enumerated_columns":
        cand = [q for q in pool if q.count(".") >= 3 or q.count(",") >= 4] or pool
    else:
        cand = pool
    picks = rng.sample(cand, min(k, len(cand)))
    return "\n\n".join(f"EXAMPLE {i+1}:\n{q}" for i, q in enumerate(picks))


# Extra per-bucket instruction for the question writer. `boundary` needs its own
# because the general "don't restate edge rules" guidance loses to the gate: the
# model states the rule to guarantee an unambiguous reading, which hands the
# solver the answer. Measured: 7/7 boundary items solved before this.
BUCKET_RULES = {
    "boundary": (
        "CRITICAL for this item: do NOT state how to handle the edge. Never write "
        "'including those with no trips', 'treat X as 0', 'include all tied', or "
        "'even if they have none'. Use a plain universal phrase -- 'for each "
        "station', 'every member', 'all plans' -- and stop there. 'For each "
        "station' already means all of them; saying so again turns the trap into a "
        "free answer. The reading stays unambiguous because 'for each' admits no "
        "second interpretation."),
}


SQL_PROMPT = """You are writing a GOLD SQL query for a text-to-SQL training set.

Database schema (SQLite):
{schema}

Column facts sampled from the data:
{profile}

Write ONE SQLite SELECT query against this schema.

Requirement for this item:
{template}

**Centre the query on these tables** (you may join others only if needed):
{tables}

**The headline measure must be of this kind:** {measure}

{budget}

Real gold queries from this benchmark, to match in shape and complexity:
{sql_exemplars}

Rules:
- It must run on SQLite as written and return at least 1 row.
- Give every output column a clear snake_case alias.
- Do not invent tables or columns. Use only what the schema lists.
- Prefer real complexity (CTEs, window functions, conditional aggregation) over
  length for its own sake.
- Return ONLY the SQL in a ```sql fenced block. No commentary.
{trap_ask}
"""

TRAP_BUCKETS = {"boundary"}

TRAP_ASK = """
THEN, in a SECOND ```sql block, write the NAIVE query: what a careless analyst
would write for the same question, getting the edge wrong (an inner join that
drops empty members, a plain GROUP BY that keeps or loses the NULL group). It
must run. The two results MUST differ -- that difference is the whole point of
the item, and the item is thrown away if they come out the same."""

QUESTION_PROMPT = """You are writing the natural-language question that this GOLD SQL answers,
for a text-to-SQL training set. Match the house style of the examples below.

Real questions from this benchmark family, to imitate in register and density:

{exemplars}

Now your item.

Schema (SQLite):
{schema}

Gold SQL:
```sql
{sql}
```

It returns {nrows} row(s) and {ncols} column(s):
{preview}

Write the question a data analyst would have asked to get exactly this.

Rules:
- ONE defensible reading. A competent analyst with the schema must be able to
  tell what the output should look like -- how many rows, and which columns.
- Name every quantity the output contains. If the result has {ncols} columns, ask
  for {ncols} things. Listing deliverables explicitly is in style (see examples).
- DO specify metric definitions when they are not obvious: which rows go in a
  denominator, what counts as "completed", how a rate is computed. The examples
  do this constantly and it is what makes the question answerable.
- EVERY superlative must name the quantity it ranks by AND its scope. "The
  highest-paid technician" is unusable: highest paid by hourly rate or by total
  cost, and highest in each borough or overall? Write "the technician with the
  highest hourly rate in each borough". The same goes for "busiest", "largest",
  "best", "top", "most active" -- each needs a measure and a scope.
- Do NOT name relational mechanics. Never write "dense ranking", "rank", "join",
  "distinct", "group by", "include X even if it has no Y", or "eligible for this
  comparison". Those are SQL tells. Say what the business rule is and let the
  mechanics follow: not "using dense ranking so ties share a rank" but "report
  every station that reaches that figure".
- Do not explain how to handle edge cases the business meaning already settles.
  "For each member, their trip count" already implies members with no trips show
  a zero; spelling that out turns a real trap into a free answer.
- No table names, column names or SQL aliases. Business meaning only.
- State a row count only when idiomatic ("the top 25 members", "which single
  day"), never as "which 25 rows should appear".
- Length: aim for {wmin}-{wmax} words, two or more sentences.
- Return ONLY the question, one paragraph, no preamble.
{bucket_rule}
"""

GATE_PROMPT = """Read this question about a database and state what its answer must look like.
You are NOT being asked to answer it or to write SQL.

Schema (SQLite):
{schema}

Question:
{question}

Reply with JSON only:
{{"rows": <integer if the question pins an exact row count, else null>,
 "row_grain": "<what one row of the answer represents>",
 "columns": ["<what each column holds>", ...],
 "ambiguous": <true if the question has more than one defensible reading>,
 "why": "<one sentence>"}}
"""


def fences(text: str, lang: str = "sql") -> list[str]:
    out = re.findall(rf"```{lang}\s*(.*?)```", text, re.S) or re.findall(r"```\s*(.*?)```", text, re.S)
    return [x.strip().rstrip(";") for x in out]


def fence(text: str, lang: str = "sql") -> str:
    m = re.search(rf"```{lang}\s*(.*?)```", text, re.S) or re.search(r"```\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip().rstrip(";")


def schema_text(db: sqlite3.Connection) -> str:
    out = []
    for (name, sql) in db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
        out.append(" ".join((sql or "").split()))
    return "\n".join(out)


def table_names(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def fk_graph(db: sqlite3.Connection) -> dict[str, set[str]]:
    g = {t: set() for t in table_names(db)}
    for t in g:
        for r in db.execute(f'PRAGMA foreign_key_list("{t}")'):
            ref = r[2]
            if ref in g:
                g[t].add(ref); g[ref].add(t)
    return g


def has_fk_gap(path: Path) -> bool:
    """True if some FK parent has rows no child references.

    `boundary` traps need exactly this. A fully saturated schema makes LEFT and
    INNER JOIN agree, so the naive variant always matches the gold and every
    retry is wasted. 77% of sampled SynSQL databases pass before population;
    populate_db.py holds rows back so filled ones pass by construction.
    """
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        ts = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t_ in ts:
            for r in con.execute(f'PRAGMA foreign_key_list("{t_}")'):
                par, pc, cc = r[2], r[4], r[3]
                if par not in ts:
                    continue
                if not pc:
                    pk = [x[1] for x in con.execute(f'PRAGMA table_info("{par}")') if x[5]]
                    pc = pk[0] if pk else None
                if not pc:
                    continue
                try:
                    if con.execute(
                            f'SELECT 1 FROM "{par}" p WHERE NOT EXISTS (SELECT 1 FROM '
                            f'"{t_}" c WHERE c."{cc}"=p."{pc}") LIMIT 1').fetchone():
                        return True
                except sqlite3.Error:
                    pass
        return False
    finally:
        con.close()


def connected_subsets(graph: dict[str, set[str]], k: int) -> list[tuple[str, ...]]:
    """Every connected k-subset of the FK graph, deduplicated.

    Enumerating lets us draw (measure, focus) combinations WITHOUT replacement.
    Random draws collide by the birthday paradox: at ~60 items per database from a
    ~900-combination space, repeats become common, and the model has no memory of
    what it already wrote to compensate.
    """
    out = set()

    def grow(cur: frozenset):
        if len(cur) == k:
            out.add(tuple(sorted(cur)))
            return
        for t_ in cur:
            for nb in graph[t_] - cur:
                grow(cur | {nb})

    for seed in graph:
        grow(frozenset({seed}))
    return sorted(out)


def connected_focus(graph: dict[str, set[str]], rng, k: int = 3) -> list[str]:
    """A CONNECTED set of tables, grown along foreign keys.

    Sampling k arbitrary tables produced incoherent items: given
    (technicians, promos, weather_daily) -- which share no join path -- the model
    bolted unrelated aggregates into one row. Walking the FK graph keeps the
    forced variety while guaranteeing the tables can actually be related.
    """
    seed = rng.choice([t for t, n in graph.items() if n - {t}] or list(graph))
    chosen = [seed]
    frontier = set(graph[seed]) - {seed}        # self-FKs (members.referred_by)
    while len(chosen) < k and frontier:
        nxt = rng.choice(sorted(frontier))
        chosen.append(nxt)
        frontier |= graph[nxt]
        frontier -= set(chosen)
    return chosen


def profile_text(db: sqlite3.Connection, per_table: int = 3) -> str:
    """Cheap data facts, no LLM -- the same idea as scripts/compute_profile.py."""
    lines = []
    for (t,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        n = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        lines.append(f"{t}: {n} rows")
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')]
        for c in cols[:per_table + 3]:
            try:
                vals = [r[0] for r in db.execute(
                    f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL LIMIT 4')]
                nulls = db.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" IS NULL').fetchone()[0]
            except sqlite3.Error:
                continue
            tag = f"  {t}.{c}: e.g. {', '.join(str(v)[:24] for v in vals)}"
            if nulls:
                tag += f"  [{nulls} NULLs]"
            lines.append(tag)
    return "\n".join(lines)


# Spider 2.0's largest gold result is 2,000 rows (see config.result_rows_max).
# A synthesized gold far above that is a cross-join blowup, not a question an
# analyst would ask: one such item came back with 2,353,589 rows.
MAX_GOLD_ROWS = 2000


def run_sql(db: sqlite3.Connection, sql: str, limit: int = 15):
    cur = db.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(MAX_GOLD_ROWS + 1)
    head = [",".join(cols)]
    for r in rows[:limit]:
        head.append(",".join("" if v is None else str(v) for v in r))
    # Digest over EVERY fetched row, not the 15-row preview: the trap check
    # compares results, and comparing previews called a 2.3M-row result equal to
    # a different one because both previews were truncated.
    digest = hashlib.sha256(
        repr([tuple(r) for r in rows]).encode()).hexdigest()
    return len(rows), len(cols), cols, "\n".join(head), digest


USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
# Per stage, so we can see which one to economise on. Stage A's output is
# execution-verified, stage B's is not -- a cheaper model is far safer on A.
BY_STAGE: dict[str, dict] = {}


def ask(client, model, prompt, temperature, max_tokens=1600, stage="?"):
    r = client.chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    s = BY_STAGE.setdefault(stage, {"in": 0, "out": 0, "calls": 0, "model": model})
    if r.usage:                     # recorded so spend is auditable from the data
        USAGE["prompt_tokens"] += r.usage.prompt_tokens
        USAGE["completion_tokens"] += r.usage.completion_tokens
        s["in"] += r.usage.prompt_tokens
        s["out"] += r.usage.completion_tokens
    USAGE["calls"] += 1
    s["calls"] += 1
    return r.choices[0].message.content or ""


def key_spend(base_url: str | None, key: str) -> float | None:
    """Cumulative dollars spent on this key, from the gateway itself.

    LiteLLM exposes /key/info, so we never have to maintain a price table or
    guess what a model costs -- the number is whatever the gateway billed.
    Returns None when the endpoint is not a LiteLLM proxy.
    """
    if not base_url:
        return None
    try:
        import urllib.request
        url = base_url.rstrip("/").removesuffix("/v1") + "/key/info"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return float((json.load(r).get("info") or {}).get("spend"))
    except Exception:
        return None


def sha256_file(path: Path, limit: int = 1 << 30) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            if h.block_size and f.tell() > limit:
                break
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).resolve().parent).stdout.strip() or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="one database")
    ap.add_argument("--db-dir", help="directory of .sqlite files; items rotate "
                                     "round-robin so coverage stays even")
    ap.add_argument("--require-fk-gap", action="store_true",
                    help="skip databases where every FK parent is fully "
                         "referenced. Measured: on such a schema LEFT and INNER "
                         "JOIN agree, so `boundary` burns every retry -- 18 of 21 "
                         "attempts failed that way on a saturated database.")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=None, help="omit for api.openai.com")
    ap.add_argument("--model", default="gpt-5.4",
                    help="stage B (question phrasing). Quality here is NOT "
                         "verifiable -- a bad question is ambiguous, the gate "
                         "rejects it, and the stage-A spend is wasted.")
    ap.add_argument("--sql-model", default=None,
                    help="stage A (gold SQL); defaults to --model. Safe place "
                         "to economise: the output is execution-verified.")
    ap.add_argument("--gate-base-url", default=None, help="default: same as --base-url")
    ap.add_argument("--gate-model", default=None, help="default: --model (NOT recommended)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--retries", type=int, default=2, help="retries when the gold SQL fails")
    ap.add_argument("--exemplars",
                    default="../Spider2/spider2-lite/spider2-lite.jsonl",
                    help="question file for style exemplars; local* are always excluded")
    ap.add_argument("--n-exemplars", type=int, default=3)
    ap.add_argument("--hard-share", type=float, default=0.30,
                    help="fraction of items generated against the HARD budget, "
                         "targeting the >=5-column shape that is 2.2x "
                         "over-represented among questions we never solve")
    ap.add_argument("--sql-exemplars", type=int, default=2,
                    help="real gold queries shown to stage A (0 disables)")
    ap.add_argument("--buckets", help="comma-separated subset of "
                    + ",".join(TEMPLATES) + " (default: cycle all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-spend", type=float, default=0.0,
                    help="abort once this key's CUMULATIVE spend (as the gateway "
                         "reports it) reaches this many dollars. 0 disables.")
    ap.add_argument("--spend-check-every", type=int, default=5)
    ap.add_argument("--workers", type=int, default=16,
                    help="items in flight. The three stages are sequential "
                         "within an item but items are independent; serialising "
                         "them turned 1,000 questions into a 6-hour job.")
    ap.add_argument("--resume", action="store_true",
                    help="keep items already in --out and generate only what is "
                         "missing, so a rerun never pays for the same item twice")
    ap.add_argument("--db-note", default="",
                    help="how this database was obtained, e.g. "
                         "'scripts/make_synth_db.py --seed 7' or 'synsql/<db_id>'. "
                         "Recorded per item so the set stays reproducible without "
                         "storing the database.")
    args = ap.parse_args()

    key = os.environ.get("OPENAI_API_KEY", "EMPTY")
    client = OpenAI(base_url=args.base_url, api_key=key)
    gate_client = (client if not args.gate_base_url
                   else OpenAI(base_url=args.gate_base_url, api_key=key))
    gate_model = args.gate_model or args.model
    sql_model = args.sql_model or args.model
    if gate_model == args.model and args.gate_base_url is None:
        print("WARNING: gate uses the same model that phrased the question -- "
              "agreement will be self-confirming. Pass --gate-model/--gate-base-url.",
              file=sys.stderr)

    if args.db_dir:
        db_paths = sorted(Path(args.db_dir).glob("*.sqlite"))
    elif args.db:
        db_paths = [Path(args.db)]
    else:
        raise SystemExit("pass --db or --db-dir")
    if not db_paths:
        raise SystemExit(f"no .sqlite files under {args.db_dir}")

    rng = random.Random(args.seed)
    from nl2sql.config import GOLD_SQL_DIR
    sqlpool = load_sql_exemplars(Path(GOLD_SQL_DIR)) if args.sql_exemplars else []
    hardpool = load_hard_sql_exemplars(Path(GOLD_SQL_DIR)) if args.sql_exemplars else []
    print(f"gold-SQL exemplars for stage A: {len(sqlpool)} ordinary, "
          f"{len(hardpool)} hard (both non-local; 0 from the 24 local gold files)")
    print(f"hard share: {args.hard_share:.0%} of items target the >=5-column profile")
    pool = load_exemplars(Path(args.exemplars)) if args.exemplars else []
    print(f"style exemplars: {len(pool)} non-local questions from "
          f"{Path(args.exemplars).name} (0 from the 135 local test set)")

    if args.require_fk_gap:
        keep = [p_ for p_ in db_paths if has_fk_gap(p_)]
        print(f"FK-gap screen: {len(keep)}/{len(db_paths)} databases have an "
              f"unreferenced-parent gap; the rest are skipped")
        db_paths = keep or db_paths
    print(f"{len(db_paths)} database(s)")

    # Per-database state, built on first use: a 300-database run should not pay
    # for profiling all of them up front.
    cache: dict[Path, dict] = {}

    def db_state(path: Path) -> dict:
        if path not in cache:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            sch = schema_text(con)   # read once; workers open their own handles
            graph = fk_graph(con)
            fsets = connected_subsets(graph, 3) or [tuple(sorted(graph))[:3]]
            cb = {}
            for b in TEMPLATES:
                q = [(m, f) for f in fsets for m in MEASURES]
                random.Random(args.seed * 977
                              + (stable_hash(f"{b}|{path.name}") % 977)).shuffle(q)
                cb[b] = q
            prof = profile_text(con)
            con.close()
            cache[path] = {
                "schema": sch, "profile": prof,
                "focus_sets": fsets, "combos": cb,
                "prov": {"db_file": path.name, "db_note": args.db_note,
                         "db_sha256": sha256_file(path),
                         "schema_sha256": hashlib.sha256(sch.encode()).hexdigest()},
            }
        return cache[path]

    # Run-level provenance; the per-database half is merged in per item.
    run_prov = {
        "synth_seed": args.seed,
        "model": args.model,
        "sql_model": sql_model,
        "gate_model": gate_model,
        "exemplar_file": Path(args.exemplars).name if args.exemplars else None,
        "n_exemplars": args.n_exemplars if pool else 0,
        "temperature": args.temperature,
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "script": "scripts/synth_questions.py",
    }
    if not args.db_note:
        print("NOTE: no --db-note given; items will not say how to rebuild the database.")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.resume and out_path.exists():
        for line in out_path.open():
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
        print(f"resume: {len(done)} items already in {out_path.name}, skipping those")

    spend0 = key_spend(args.base_url, key)
    if spend0 is not None:
        print(f"key spend so far: ${spend0:.4f}"
              + (f" / cap ${args.max_spend:.2f}" if args.max_spend else " (no --max-spend set)"))
        if args.max_spend and spend0 >= args.max_spend:
            raise SystemExit(f"ABORT: already at or over the ${args.max_spend:.2f} cap")

    names = args.buckets.split(",") if args.buckets else list(TEMPLATES)
    for b in names:
        if b not in TEMPLATES:
            raise SystemExit(f"unknown bucket {b!r}; choose from {list(TEMPLATES)}")
    kept = 0
    recs_seen = []
    # Pre-assign every deterministic choice BEFORE going concurrent, so the
    # combination queues are drained in index order and --resume still
    # reproduces the same items.
    plan = []
    for i in range(args.n):
        if f"syn{i:04d}" in done:
            continue
        bucket = names[i % len(names)]
        dbp = db_paths[i % len(db_paths)]
        st = db_state(dbp)
        queue = st["combos"][bucket]
        if not queue:
            queue.extend([(m, f_) for f_ in st["focus_sets"] for m in MEASURES])
            random.Random(args.seed + i).shuffle(queue)
        measure, focus_t = queue.pop()
        is_hard = (i % 10) < round(args.hard_share * 10) and bool(hardpool)
        plan.append(dict(i=i, bucket=bucket, dbp=dbp, measure=measure,
                         focus=list(focus_t), is_hard=is_hard))
    print(f"{len(plan)} items to generate, {args.workers} workers")

    write_lock, tally_lock = threading.Lock(), threading.Lock()
    stop = threading.Event()

    def work(job):
        i, bucket, dbp = job["i"], job["bucket"], job["dbp"]
        st = db_state(dbp)
        schema, profile = st["schema"], st["profile"]
        focus, measure, is_hard = job["focus"], job["measure"], job["is_hard"]
        irng = random.Random(args.seed * 100_003 + i)
        budget_d = (HARD_BUDGETS if is_hard else BUDGETS)[bucket]
        ex_pool = hardpool if is_hard else sqlpool
        rec = {"id": f"syn{i:04d}", "bucket": bucket, "focus_tables": focus,
               "measure": measure, "hard": is_hard,
               "provenance": {**run_prov, **st["prov"]}}
        db = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)   # per thread
        try:
            sql = nrows = ncols = preview = gdig = None
            for _ in range(args.retries + 1):
                raw = ask(client, sql_model, SQL_PROMPT.format(
                    schema=schema, profile=profile, template=TEMPLATES[bucket],
                    tables=", ".join(focus), measure=measure,
                    budget=BUDGET.format(**budget_d)
                            + ("\n\n" + HARD_NOTE if is_hard else ""),
                    sql_exemplars="\n\n".join(
                        f"-- example {j+1}\n{q}" for j, q in
                        enumerate(irng.sample(ex_pool, min(args.sql_exemplars, len(ex_pool)))))
                    or "(none)",
                    trap_ask=TRAP_ASK if bucket in TRAP_BUCKETS else ""),
                    args.temperature, 2400, stage="A_sql")
                blocks = fences(raw)
                cand = blocks[0] if blocks else fence(raw)
                try:
                    nrows, ncols, cols, preview, gdig = run_sql(db, cand)
                    if nrows == 0:
                        raise ValueError("gold returned 0 rows")
                    if nrows > MAX_GOLD_ROWS:
                        raise ValueError(
                            f"gold returns >{MAX_GOLD_ROWS} rows ({nrows}+); "
                            "a blown-up join, not an analyst question")
                    if bucket in TRAP_BUCKETS:
                        if len(blocks) < 2:
                            raise ValueError("no naive variant returned")
                        nr, nc, _, _, ndig = run_sql(db, blocks[1])
                        if ndig == gdig:
                            raise ValueError(
                                f"trap not real: naive gives an identical {nr}x{nc} result")
                        rec["naive_sql"] = blocks[1]
                        rec["naive_rows"], rec["naive_cols"] = nr, nc
                    sql = cand
                    break
                except Exception as e:
                    rec.setdefault("sql_attempts", []).append(
                        {"sql": cand[:400], "error": f"{type(e).__name__}: {e}"[:200]})
            if sql is None:
                rec["status"] = "sql_failed"
                return rec
            rec.update(gold_sql=sql, gold_rows=nrows, gold_cols=ncols,
                       gold_columns=cols, gold_preview=preview)
            ex = pick_exemplars(pool, bucket, irng, args.n_exemplars) if pool else "(none)"
            rec["question"] = " ".join(ask(client, args.model, QUESTION_PROMPT.format(
                exemplars=ex, schema=schema, sql=sql, nrows=nrows, ncols=ncols,
                preview=preview, wmin=40, wmax=75,
                bucket_rule=BUCKET_RULES.get(bucket, "")), args.temperature,
                1600, stage="B_question").split())
            graw = ask(gate_client, gate_model, GATE_PROMPT.format(
                schema=schema, question=rec["question"]), 0.0, 2500, stage="C_gate")
            try:
                g = json.loads(fence(graw, "json"))
            except Exception:
                g = {"parse_error": graw[:300]}
            rec["gate"] = g
            rows_ok = g.get("rows") is None or g.get("rows") == nrows
            cols_ok = isinstance(g.get("columns"), list) and len(g["columns"]) == ncols
            rec["gate_rows_ok"], rec["gate_cols_ok"] = rows_ok, cols_ok
            rec["gate_committed"] = g.get("rows") is not None
            rec["status"] = ("pass" if rows_ok and cols_ok and not g.get("ambiguous")
                             else "gated_out")
            return rec
        finally:
            db.close()

    kept = 0
    with out_path.open("a" if args.resume else "w") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as ex_pool_:
            futs = {ex_pool_.submit(work, j): j for j in plan}
            for k, fut in enumerate(as_completed(futs)):
                if stop.is_set():
                    break
                try:
                    rec = fut.result()
                except Exception as e:
                    print(f"  syn{futs[fut]['i']:04d}: {type(e).__name__}: {str(e)[:90]}")
                    continue
                with write_lock:
                    recs_seen.append(rec)
                    f.write(json.dumps(rec) + "\n"); f.flush()
                with tally_lock:
                    if rec["status"] == "pass":
                        kept += 1
                if rec["status"] == "sql_failed":
                    print(f"{rec['id']} [{rec['bucket']}] SQL FAILED")
                else:
                    g = rec.get("gate") or {}
                    print(f"{rec['id']} [{rec['bucket']:19s}]{'H' if rec['hard'] else ' '}"
                          f"{rec['gold_rows']:6d}x{rec['gold_cols']} gold | "
                          f"gate rows={g.get('rows')} cols={len(g.get('columns') or [])} "
                          f"amb={g.get('ambiguous')} -> {rec['status']}")
                if args.max_spend and k % args.spend_check_every == 0 and k:
                    now = key_spend(args.base_url, key)
                    if now is not None and now >= args.max_spend:
                        print(f"\nSTOPPING: key spend ${now:.4f} reached the "
                              f"${args.max_spend:.2f} cap. Rerun with --resume.")
                        stop.set()

    strict = sum(1 for r in recs_seen if r.get("gate_committed") and r["status"] == "pass")
    print(f"\nwrote {out_path}: {kept}/{args.n} passed the gate ({kept/max(args.n,1):.0%})")
    spend1 = key_spend(args.base_url, key)
    print(f"  tokens: {USAGE['prompt_tokens']:,} in / {USAGE['completion_tokens']:,} out "
          f"over {USAGE['calls']} calls")
    for st_ in sorted(BY_STAGE):
        s = BY_STAGE[st_]
        print(f"    {st_:12s} {s['model']:26s} {s['calls']:4d} calls  "
              f"{s['in']:8,d} in / {s['out']:7,d} out")
    if spend0 is not None and spend1 is not None:
        n_new = len([r for r in recs_seen])
        print(f"  spend: ${spend1-spend0:.4f} this run (${spend1:.4f} cumulative)"
              + (f" = ${(spend1-spend0)/n_new:.4f}/item" if n_new else ""))
    print(f"  of those, {strict} are STRICT passes (the gate committed to a row count "
          f"and matched); the rest matched on column count alone")

if __name__ == "__main__":
    main()
