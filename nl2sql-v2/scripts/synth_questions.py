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
import subprocess
import random
import re
import sqlite3
import sys
from pathlib import Path

from openai import OpenAI

# ── failure-mode templates ────────────────────────────────────────────────
# Stratified from the measured taxonomy (plan §3.2). Each bucket teaches the
# judge a different discrimination; counts are lane-failures on the 135.
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


def ask(client, model, prompt, temperature, max_tokens=1600):
    r = client.chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    if r.usage:                     # recorded so spend is auditable from the data
        USAGE["prompt_tokens"] += r.usage.prompt_tokens
        USAGE["completion_tokens"] += r.usage.completion_tokens
    USAGE["calls"] += 1
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
    ap.add_argument("--db", required=True)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=None, help="omit for api.openai.com")
    ap.add_argument("--model", default="gpt-5.4")
    ap.add_argument("--gate-base-url", default=None, help="default: same as --base-url")
    ap.add_argument("--gate-model", default=None, help="default: --model (NOT recommended)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--retries", type=int, default=2, help="retries when the gold SQL fails")
    ap.add_argument("--exemplars",
                    default="../Spider2/spider2-lite/spider2-lite.jsonl",
                    help="question file for style exemplars; local* are always excluded")
    ap.add_argument("--n-exemplars", type=int, default=3)
    ap.add_argument("--buckets", help="comma-separated subset of "
                    + ",".join(TEMPLATES) + " (default: cycle all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-spend", type=float, default=0.0,
                    help="abort once this key's CUMULATIVE spend (as the gateway "
                         "reports it) reaches this many dollars. 0 disables.")
    ap.add_argument("--spend-check-every", type=int, default=5)
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
    if gate_model == args.model and args.gate_base_url is None:
        print("WARNING: gate uses the same model that phrased the question -- "
              "agreement will be self-confirming. Pass --gate-model/--gate-base-url.",
              file=sys.stderr)

    db = sqlite3.connect(args.db)
    schema, profile = schema_text(db), profile_text(db)
    graph = fk_graph(db)
    rng = random.Random(args.seed)
    focus_sets = connected_subsets(graph, 3)
    combos = {}          # bucket -> shuffled queue of (measure, focus) pairs
    for b in TEMPLATES:
        pool_b = [(m, f) for f in focus_sets for m in MEASURES]
        random.Random(args.seed * 977 + hash(b) % 977).shuffle(pool_b)
        combos[b] = pool_b
    print(f"combination space: {len(focus_sets)} connected 3-table sets x "
          f"{len(MEASURES)} measures = {len(focus_sets)*len(MEASURES)} per bucket")
    pool = load_exemplars(Path(args.exemplars)) if args.exemplars else []
    print(f"style exemplars: {len(pool)} non-local questions from "
          f"{Path(args.exemplars).name} (0 from the 135 local test set)")

    # Provenance: enough to reproduce an item without keeping the database.
    # The schema hash identifies the schema however it was built; db_note says
    # how to rebuild it; the seeds make generation deterministic.
    prov = {
        "db_file": Path(args.db).name,
        "db_note": args.db_note,
        "db_sha256": sha256_file(Path(args.db)),
        "schema_sha256": hashlib.sha256(schema.encode()).hexdigest(),
        "synth_seed": args.seed,
        "model": args.model,
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
    with out_path.open("a" if args.resume else "w") as f:
        for i in range(args.n):
            if f"syn{i:04d}" in done:
                continue
            if (args.max_spend and i and i % args.spend_check_every == 0):
                now = key_spend(args.base_url, key)
                if now is not None and now >= args.max_spend:
                    print(f"\nSTOPPING at item {i}: key spend ${now:.4f} reached the "
                          f"${args.max_spend:.2f} cap. Rerun with --resume to continue.")
                    break
            bucket = names[i % len(names)]
            irng = random.Random(args.seed * 100_003 + i)   # per item, so --resume
            queue = combos[bucket]                          # reproduces exactly
            if not queue:                                   # space exhausted
                print(f"  (combination space for {bucket} exhausted; reshuffling)")
                queue.extend([(m, f) for f in focus_sets for m in MEASURES])
                irng.shuffle(queue)
            measure, focus_t = queue.pop()
            focus = list(focus_t)
            rec = {"id": f"syn{i:04d}", "bucket": bucket,
                   "focus_tables": focus, "measure": measure,
                   "provenance": prov}

            # ── stage A: gold SQL (correct by execution, retried if it fails)
            sql = nrows = ncols = preview = gdig = None
            for attempt in range(args.retries + 1):
                raw = ask(client, args.model, SQL_PROMPT.format(
                    schema=schema, profile=profile, template=TEMPLATES[bucket],
                    tables=", ".join(focus), measure=measure,
                    trap_ask=TRAP_ASK if bucket in TRAP_BUCKETS else ""),
                    args.temperature, 2400)
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
                        # Verify the trap instead of trusting it: execute the naive
                        # variant and require a genuinely different result.
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
                f.write(json.dumps(rec) + "\n"); f.flush()
                print(f"{rec['id']} [{bucket}] SQL FAILED"); continue
            rec.update(gold_sql=sql, gold_rows=nrows, gold_cols=ncols,
                       gold_columns=cols, gold_preview=preview)

            # ── stage B: the question
            ex = pick_exemplars(pool, bucket, irng, args.n_exemplars) if pool else "(none)"
            rec["question"] = " ".join(ask(client, args.model, QUESTION_PROMPT.format(
                exemplars=ex, schema=schema, sql=sql, nrows=nrows, ncols=ncols,
                preview=preview, wmin=40, wmax=75,
                bucket_rule=BUCKET_RULES.get(bucket, "")), args.temperature).split())

            # ── stage C: the gate -- intent agreement, blind to the gold SQL
            # 2500, not 800: the gate must enumerate one entry per column, and a
            # 12-column answer truncates mid-JSON at 800, which reads as a
            # rejection rather than as the bug it is.
            graw = ask(gate_client, gate_model, GATE_PROMPT.format(
                schema=schema, question=rec["question"]), 0.0, 2500)
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
            kept += rec["status"] == "pass"
            recs_seen.append(rec)
            f.write(json.dumps(rec) + "\n"); f.flush()
            print(f"{rec['id']} [{bucket:19s}] {nrows:5d}x{ncols} gold | "
                  f"gate rows={g.get('rows')} cols={len(g.get('columns') or [])} "
                  f"amb={g.get('ambiguous')} -> {rec['status']}")

    strict = sum(1 for r in recs_seen if r.get("gate_committed") and r["status"] == "pass")
    print(f"\nwrote {out_path}: {kept}/{args.n} passed the gate ({kept/max(args.n,1):.0%})")
    spend1 = key_spend(args.base_url, key)
    print(f"  tokens: {USAGE['prompt_tokens']:,} in / {USAGE['completion_tokens']:,} out "
          f"over {USAGE['calls']} calls")
    if spend0 is not None and spend1 is not None:
        n_new = len([r for r in recs_seen])
        print(f"  spend: ${spend1-spend0:.4f} this run (${spend1:.4f} cumulative)"
              + (f" = ${(spend1-spend0)/n_new:.4f}/item" if n_new else ""))
    print(f"  of those, {strict} are STRICT passes (the gate committed to a row count "
          f"and matched); the rest matched on column count alone")
    db.close()


if __name__ == "__main__":
    main()
