#!/usr/bin/env python3
"""Precompute what one row of each table is.

Stage 1 (data only): for every table, find ALL smallest column sets (up to
--max-cols) whose values are distinct on every row. These are facts.
Stage 2 (--choose, needs an LLM endpoint): a model proposes the intended key
from what the table means, and the proposal is kept only if the data confirms
it is unique (one retry). It sees the table and the rest of the schema, never
the benchmark questions.

Usage (from repo root):
    uv run --project nl2sql-v2 python scripts/compute_keys.py --out-dir spider2-dce/output/keys
    uv run --project nl2sql-v2 python scripts/compute_keys.py --out-dir spider2-dce/output/keys \
        --choose --endpoint http://<node>:<port>/v1 --model <model>
"""

import argparse
import itertools
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
from nl2sql.config import DCE_PROJECT_DIR  # noqa: E402

def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_keys(con, table: str, columns: list[tuple[str, str]], max_cols: int,
               row_limit: int, budget_s: float) -> dict:
    """All minimal unique column sets of the smallest size that has any."""
    n = con.execute(f"SELECT COUNT(*) FROM db.{q(table)}").fetchone()[0]
    out = {"n_rows": n, "candidates": [], "complete": True, "duplicate_rows": None}
    if n == 0 or n > row_limit:
        out["complete"] = False
        return out
    # work on an in-memory text copy: fast, and immune to SQLite's loose typing
    sel = ", ".join(f"CAST({q(c)} AS VARCHAR) AS {q(c)}" for c, _ in columns)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _t AS SELECT {sel} FROM db.{q(table)}")
    aggs = ", ".join(f"COUNT(DISTINCT {q(c)}), COUNT(*) - COUNT({q(c)})" for c, _ in columns)
    vals = con.execute(f"SELECT {aggs} FROM _t").fetchone()
    distinct = {c: vals[2 * i] for i, (c, _) in enumerate(columns)}
    nulls = {c: vals[2 * i + 1] for i, (c, _) in enumerate(columns)}
    out["duplicate_rows"] = n - con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT * FROM _t)").fetchone()[0]
    # identifiers are fully populated and hold no fractional numbers. Judged
    # from the values, not the declared type: SQLite ids are often NUMERIC.
    frac = con.execute("SELECT " + ", ".join(
        f"COUNT(*) FILTER (WHERE regexp_full_match({q(c)}, '-?[0-9]*\\.[0-9]*[1-9][0-9]*'))"
        for c, _ in columns) + " FROM _t").fetchone()
    cand = [c for i, (c, t) in enumerate(columns)
            if nulls[c] == 0 and frac[i] == 0 and "BLOB" not in (t or "").upper()]
    order = [c for c, _ in columns]

    def product(combo):
        p = 1
        for c in combo:
            p *= distinct[c]
        return p

    t0 = time.time()
    for k in range(1, max_cols + 1):
        found = []
        # tightest first, so that if the time budget runs out the structural
        # keys (distinct counts multiplying to about the row count) were tried
        for combo in sorted(itertools.combinations(cand, k), key=product):
            if product(combo) < n:
                continue
            if time.time() - t0 > budget_s:
                out["complete"] = False
                break
            cols = ", ".join(q(c) for c in combo)
            m = con.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT {cols} FROM _t)").fetchone()[0]
            if m == n:
                found.append(sorted(combo, key=order.index))
        if found:
            out["candidates"] = found
            break
        if not out["complete"]:
            break
    con.execute("DROP TABLE IF EXISTS _t")
    return out


CHOOSE_PROMPT = """A database table has no declared primary key. Work out its \
intended key: the columns that say what one row of this table IS.

Identifiers, codes, names and dates of the thing being recorded belong in a key; \
measurements and amounts recorded about it do not. A column set can be unique in the \
data by coincidence — a timestamp or an amount that happens never to repeat — without \
being the key.

Database tables (name: columns):
{overview}

Table: {table}  ({n_rows} rows)
Columns (type, distinct values):
{columns}
Declared foreign keys: {fks}
Sample rows:
{samples}

Smallest column sets that are unique on every row of the current data (hints only; \
the intended key may be one of these, or a larger set):
{candidates}

First reason about what one row represents, then name the key. Your proposal will be \
checked against the data. If the table has no key (rows can legitimately repeat), \
return an empty list.

Reply with JSON only, fields in this order:
{{"reasoning": "<two or three sentences>", \
"row_is": "<one short phrase: what one row represents>", \
"key": ["<column>", ...]}}"""

RETRY_NOTE = """

Your previous proposal ({key}) is not a key: {dups} of {n_rows} rows share their \
values with another row. Propose a different key, or an empty list if the table has \
none."""


def ask(client, model, prompt) -> dict:
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0.0, max_tokens=4000,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}}
        if "qwen" in model.lower() else None)
    text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "",
                  flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def choose_key(client, model, con, table, columns, base_prompt, n_rows) -> dict:
    """The model proposes a key from what the table means; the data confirms
    or rejects it. One retry after a rejection."""
    names = {c.lower(): c for c, _ in columns}
    prompt, out = base_prompt, {"attempts": []}
    for _ in range(2):
        ans = ask(client, model, prompt)
        key = [names[str(c).lower()] for c in ans.get("key") or []
               if str(c).lower() in names]
        out["row_is"] = str(ans.get("row_is", ""))[:200]
        out["choice_reason"] = str(ans.get("reasoning", ""))[:400]
        if not key:
            out["attempts"].append({"key": [], "unique": None})
            out["chosen"] = None
            return out
        cols = ", ".join(f"CAST({q(c)} AS VARCHAR)" for c in key)
        m = con.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT {cols} "
                        f"FROM db.{q(table)})").fetchone()[0]
        out["attempts"].append({"key": key, "unique": m == n_rows})
        if m == n_rows:
            out["chosen"] = key
            return out
        prompt = base_prompt + RETRY_NOTE.format(key=", ".join(key), dups=n_rows - m,
                                                 n_rows=n_rows)
    out["chosen"] = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--datasources", help="comma-separated yaml stems (default: all)")
    ap.add_argument("--max-cols", type=int, default=4)
    ap.add_argument("--row-limit", type=int, default=5_000_000)
    ap.add_argument("--budget-s", type=float, default=120.0)
    ap.add_argument("--choose", action="store_true")
    ap.add_argument("--endpoint")
    ap.add_argument("--model")
    args = ap.parse_args()

    import yaml
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    want = set(args.datasources.split(",")) if args.datasources else None
    client = None
    if args.choose:
        from openai import OpenAI
        client = OpenAI(base_url=args.endpoint, api_key="EMPTY", timeout=300)

    from nl2sql.config import SQLITE_DIR
    by_norm = {re.sub(r"[^a-z0-9]", "_", p.stem.lower()): p
               for p in SQLITE_DIR.glob("*.sqlite") if p.stat().st_size}
    for src in sorted((DCE_PROJECT_DIR / "output" / "databases").glob("*.yaml")):
        if want and src.stem not in want:
            continue
        # enriched yaml names are the sqlite names lowercased, non-alnum -> "_"
        if src.stem not in by_norm:
            print(f"no sqlite file for {src.stem}; skipped")
            continue
        sqlite_path = by_norm[src.stem]
        enriched = src
        declared = {}
        if enriched.exists():
            doc = yaml.safe_load(enriched.read_text())
            for cat in doc["context"]["catalogs"]:
                for s in cat["schemas"]:
                    for t in s["tables"]:
                        declared[t["name"]] = t
        path = out_dir / f"{src.stem}.json"
        result = json.loads(path.read_text()) if path.exists() else {}

        lite = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        tables = [r[0] for r in lite.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        schema = {t: [(r[1], r[2]) for r in lite.execute(f"PRAGMA table_info({q(t)})")]
                  for t in tables}
        lite.close()

        if not args.choose:
            con = duckdb.connect(":memory:")
            con.execute("INSTALL sqlite; LOAD sqlite; SET GLOBAL sqlite_all_varchar=true")
            con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
            for t in tables:
                if t in result:
                    continue
                t0 = time.time()
                try:
                    r = table_keys(con, t, schema[t], args.max_cols, args.row_limit,
                                   args.budget_s)
                except Exception as e:
                    r = {"error": str(e)[:200], "candidates": [], "complete": False}
                pk = (declared.get(t, {}).get("primary_key") or {}).get("columns")
                r["declared_pk"] = pk
                result[t] = r
                print(f"{src.stem}.{t}: rows={r.get('n_rows')} declared={pk} "
                      f"candidates={r['candidates'][:4]}"
                      f"{' …' if len(r['candidates']) > 4 else ''} "
                      f"complete={r['complete']} ({time.time() - t0:.1f}s)", flush=True)
                path.write_text(json.dumps(result, indent=1))
            con.close()
            continue

        # stage 2: the model proposes the intended key, the data verifies it.
        # Tables with a declared key are included as a check of the method
        # (the prompt never shows the declared key).
        con = duckdb.connect(":memory:")
        con.execute("INSTALL sqlite; LOAD sqlite; SET GLOBAL sqlite_all_varchar=true")
        con.execute(f"ATTACH '{sqlite_path}' AS db (TYPE sqlite, READ_ONLY)")
        overview = "\n".join(f"{t}: {', '.join(c for c, _ in cols)}"
                             for t, cols in schema.items())[:6000]
        for t, r in result.items():
            if not r.get("n_rows") or "attempts" in r or r.get("error"):
                continue
            cands = r.get("candidates") or []
            rec = declared.get(t, {})
            fks = "; ".join(
                f"{', '.join(m['from_column'] for m in fk.get('mapping') or [])} -> "
                f"{str(fk.get('referenced_table', '')).split('.')[-1]}"
                for fk in rec.get("foreign_keys") or []) or "none"
            samples = "\n".join(json.dumps(s, default=str)[:400]
                                for s in (rec.get("samples") or [])[:5]) or "(none)"
            prompt = CHOOSE_PROMPT.format(
                overview=overview, table=t, n_rows=r["n_rows"],
                columns="\n".join(f"  {c} ({ty})" for c, ty in schema[t]),
                fks=fks, samples=samples,
                candidates="\n".join(f"  ({', '.join(c)})" for c in cands[:12])
                or "  (none found in up to 4 columns)")
            try:
                r.update(choose_key(client, args.model, con, t, schema[t], prompt,
                                    r["n_rows"]))
            except Exception as e:
                r["choice_error"] = str(e)[:200]
            print(f"{src.stem}.{t}: declared={r.get('declared_pk')} "
                  f"chosen={r.get('chosen')} attempts={r.get('attempts')}", flush=True)
            path.write_text(json.dumps(result, indent=1))
        con.close()

if __name__ == "__main__":
    main()
