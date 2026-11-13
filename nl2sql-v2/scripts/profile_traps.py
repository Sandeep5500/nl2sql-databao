#!/usr/bin/env python3
"""Find where each database can mislead a plausible query: the trap sites that
generate_trap_items.py writes questions around. Data only, no LLM.

  fanout         each parent row matches several child rows, so parent measures summed
                 after the join are inflated (declared or inferred one-to-many joins)
  tie_at_cutoff  ranking parents by their number of child rows ties at a top-k cutoff
  shared_name    a name column (or a first and last name pair) covers several IDs, so
                 grouping by name merges entities
  null_or_zero   a numeric column with NULLs or zeros: AVG skips NULLs, ratios divide by 0
  overlapping    category values that contain one another ('Active' / 'Inactive',
                 'Producer' / 'Executive Producer') or differ only in case or spaces
  mixed_dates    a text column holding dates in more than one format
  orphan_rows    rows of a child table whose key points at no parent row, so counting from
                 the child table alone and counting through the parent disagree
  lookalike_columns  two columns that could each answer a question but differ: several
                 dates or years in one table, or the same measure, date or reference on both
                 sides of a join (with fan-out, the agent's most common wrong-logic failure
                 on Spider2)

Each site keeps the facts a question writer needs (tables, columns, counts, examples).

Usage (NL2SQL_DATASET_DIR set to a question set from build_bird_dataset.py):
    uv run python scripts/profile_traps.py --out-dir $NL2SQL_DATASET_DIR/traps/sites
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import DCE_PROJECT_DIR, SQLITE_DIR

NAMEY = re.compile(r"name|title|label", re.I)
IDENTITY = re.compile(r"name|title|label|desc|code|comment|note|url|text|photo|image|abbr|symbol", re.I)
SAMPLE = 200_000  # rows read per look-alike comparison; enough to see a disagreement
DATE_SHAPE = re.compile(r"^9{1,4}[-/.]9{1,2}[-/.]9{1,4}")
TOP_K = (1, 3, 5, 10)


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class DB:
    """sqlite3 read-only, every query under a time budget (None when it runs out)."""

    def __init__(self, path: Path, budget_s: float):
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.con.text_factory = lambda b: b.decode("utf-8", "replace")
        self.budget_s = budget_s

    def rows(self, sql: str, params=()):
        deadline = time.time() + self.budget_s
        self.con.set_progress_handler(lambda: time.time() > deadline, 10_000)
        try:
            return self.con.execute(sql, params).fetchall()
        except sqlite3.Error:
            return None
        finally:
            self.con.set_progress_handler(None, 0)


def schema(db: DB) -> dict[str, list[tuple[str, str]]]:
    tables = [r[0] for r in db.rows("SELECT name FROM sqlite_master WHERE type = 'table' "
                                     "AND name NOT LIKE 'sqlite_%' ORDER BY name") or []]
    return {t: [(r[1], (r[2] or "").upper()) for r in db.rows(f"PRAGMA table_info({q(t)})") or []]
            for t in tables}


def is_numeric(decl: str, prof: dict) -> bool:
    if prof.get("kind") in ("integer", "decimal"):
        return True
    return not prof and any(k in decl for k in ("INT", "REAL", "NUM", "DEC", "FLOAT", "DOUBLE"))


def unique_columns(db: DB, sch: dict, keys: dict) -> dict[str, list[str]]:
    """Single columns unique on every row, per table (from compute_keys.py output,
    else checked here on id-like columns)."""
    out = {}
    for t, cols in sch.items():
        rec = keys.get(t) or {}
        found = [c[0] for c in rec.get("candidates") or [] if len(c) == 1]
        if not found and not rec:
            for c, _ in cols:
                if re.search(r"id$", c, re.I):
                    r = db.rows(f"SELECT COUNT(*) = COUNT(DISTINCT {q(c)}) AND COUNT(*) > 0 "
                                f"FROM {q(t)} WHERE {q(c)} IS NOT NULL")
                    if r and r[0][0]:
                        found.append(c)
        out[t] = found
    return out


def qcols(names: list[str], alias: str = "") -> str:
    return ", ".join(alias + q(c) for c in names)


def not_null(names: list[str], alias: str = "") -> str:
    return " AND ".join(f"{alias}{q(c)} IS NOT NULL" for c in names)


def keyref(t: str, names: list[str]) -> str:
    return f"{t}.{names[0]}" if len(names) == 1 else f"{t} ({', '.join(names)})"


def on(j: dict, x: str = "x", y: str = "y") -> str:
    return " AND ".join(f"{x}.{q(a)} = {y}.{q(b)}" for a, b in zip(j["child_cols"], j["parent_keys"]))


def unique(db: DB, t: str, names: list[str], uniq: dict) -> bool:
    """No two rows of t share a value of these columns (taken together)."""
    if len(names) == 1 and names[0] in uniq.get(t, []):
        return True
    r = db.rows(f"SELECT COUNT(*) FROM (SELECT 1 FROM {q(t)} WHERE {not_null(names)} "
                f"GROUP BY {qcols(names)} HAVING COUNT(*) > 1)")
    return bool(r) and r[0][0] == 0


def contained(db: DB, child: str, cols: list[str], parent: str, keys: list[str],
              share: float = 0.95) -> bool:
    """At least this share of the child's distinct key values (first 2000) sit in the
    parent's key."""
    vs = ", ".join(f"v{i}" for i in range(len(cols)))
    sel = ", ".join(f"{q(c)} AS v{i}" for i, c in enumerate(cols))
    r = db.rows(f"SELECT COUNT(*), SUM(({vs}) IN (SELECT {qcols(keys)} FROM {q(parent)})) "
                f"FROM (SELECT DISTINCT {sel} FROM {q(child)} WHERE {not_null(cols)} LIMIT 2000)")
    return bool(r and r[0][0] and (r[0][1] or 0) >= share * r[0][0])


def joins(db: DB, sch: dict, uniq: dict) -> list[dict]:
    """One-to-many joins onto a unique parent key: declared foreign keys (a composite key
    on all its columns), plus same-named columns whose values sit inside another table's
    unique column. A declared key with no target column points at the parent's primary
    key (SQLite's rule). A declared key holds when 75% of the child's values sit in its
    target: real keys with a few orphans measure 77-94% on BIRD, wrong declarations 0%,
    and links where the parent covers a small slice of the child 8-40%. A declared key the
    data does not bear out moves to another unique parent key holding 95% of the values,
    or is dropped. Each join keeps its columns as lists (child_cols, parent_keys) and as
    text (child_col, parent_key)."""
    found, seen, linked = [], set(), set()

    def add(child, cols, parent, keys, declared):
        seen.update((child, c, parent) for c in cols)
        if declared:
            linked.update((child, c) for c in cols)
        found.append({"parent": parent, "parent_key": ", ".join(keys), "child": child,
                      "child_col": ", ".join(cols), "parent_keys": keys, "child_cols": cols,
                      "declared": declared})

    for child in sch:
        fks = {}
        for r in db.rows(f"PRAGMA foreign_key_list({q(child)})") or []:
            fks.setdefault(r[0], []).append(r)
        for rs in fks.values():
            parent, fcols = rs[0][2], [r[3] for r in rs]
            if parent not in sch or not all(fcols):
                continue
            pks = [x[1] for x in sorted(db.rows(f"PRAGMA table_info({q(parent)})") or [],
                                        key=lambda x: x[5]) if x[5]]
            if len(rs) > 1:  # composite: all columns together, else each on its own below
                keys = [r[4] for r in rs] if all(r[4] for r in rs) else pks
                if (len(keys) == len(fcols) and unique(db, parent, keys, uniq)
                        and contained(db, child, fcols, parent, keys, 0.75)):
                    add(child, fcols, parent, keys, True)
                    continue
            for r in rs:
                fcol, pcol = r[3], r[4]
                if (child, fcol, parent) in seen:
                    continue
                target = pcol or (pks[0] if len(pks) == 1 else None)
                options = [(target, 0.75)] if target else []
                options += [(k, 0.95) for k in dict.fromkeys(uniq.get(parent, []) + pks) if k != target]
                pcol = next((k for k, share in options if unique(db, parent, [k], uniq)
                             and contained(db, child, [fcol], parent, [k], share)), None)
                if pcol:
                    add(child, [fcol], parent, [pcol], True)
    for parent, keys in uniq.items():
        for pk in keys:
            for child, cols in sch.items():
                if child == parent:
                    continue
                for c, _ in cols:
                    named = {norm(pk), norm(parent) + norm(pk), norm(parent).rstrip("s") + norm(pk)}
                    if (child, c, parent) in seen or (child, c) in linked or norm(c) not in named:
                        continue  # a declared key already says where this column points
                    if c in uniq.get(child, []):
                        continue  # one-to-one
                    if contained(db, child, [c], parent, [pk]):
                        add(child, [c], parent, [pk], False)
    return found


def fanout_sites(db: DB, sch: dict, prof: dict, uniq: dict, js: list[dict]) -> list[dict]:
    sites = []
    for j in js:
        c, by, nn = j["child"], qcols(j["child_cols"]), not_null(j["child_cols"])
        r = db.rows(f"SELECT COUNT(*), SUM(n), MAX(n) FROM (SELECT COUNT(*) AS n FROM {q(c)} "
                    f"WHERE {nn} GROUP BY {by})")
        if not r or not r[0][0]:
            continue
        parents, rows, mx = r[0]
        avg = rows / parents
        if avg < 1.2 and mx < 3:
            continue
        p = j["parent"]
        measures = [x for x, decl in sch[p] if x not in uniq.get(p, []) and not re.search(
            r"id$", x, re.I) and is_numeric(decl, (prof.get(p) or {}).get(x) or {})]
        sites.append({"kind": "fanout", **j, "parents_with_children": parents,
                      "child_rows": rows, "avg_children": round(avg, 2), "max_children": mx,
                      "parent_measures": measures[:8], "strength": round(min(avg, 10), 2)})
        top = db.rows(f"SELECT COUNT(*) AS n FROM {q(c)} WHERE {nn} "
                      f"GROUP BY {by} ORDER BY n DESC LIMIT {max(TOP_K) + 1}")
        if top:
            vals = [x[0] for x in top]
            tied = [k for k in TOP_K if len(vals) > k and vals[k - 1] == vals[k]]
            if tied and len(set(vals)) >= 3:  # a real ranking, tied at the cutoff
                sites.append({"kind": "tie_at_cutoff", **j, "ranked_by": f"COUNT of {c} rows",
                              "tied_at_k": tied, "top_counts": vals, "strength": len(tied)})
    return sites


def date_kind(c: str, p: dict) -> str | None:
    """'date' for date and datetime columns, 'year' for integer year columns."""
    if p.get("kind") in ("date", "datetime"):
        return "date"
    if (p.get("kind") == "integer" and re.search(r"year", c, re.I)
            and 1800 <= (p.get("min") or 0) <= (p.get("max") or 0) <= 2100):
        return "year"
    return None


def disagree(r) -> bool:
    """(compared rows, differing rows): differing on over 5% of rows, and on at least 5."""
    return bool(r and r[0][0] and (r[0][1] or 0) >= 5 and r[0][1] > 0.05 * r[0][0])


def lookalike_sites(db: DB, sch: dict, prof: dict, js: list[dict]) -> list[dict]:
    """Columns that could each answer a question but hold different values: several
    dates or years in one table (ordered / shipped, founded / joined), and the same
    measure, date or reference on both sides of a join (a sale's store and the product's
    store; a city's population and its country's). Names, descriptions and codes are
    left out: across a join they name different things, which no one confuses."""
    sites = []
    for t, cols in sch.items():
        groups = {}
        for c, _ in cols:
            k = date_kind(c, (prof.get(t) or {}).get(c) or {})
            if k and not re.search(r"id$", c, re.I):
                groups.setdefault(k, []).append(c)
        pairs = []
        for k, cs in groups.items():
            val = (lambda x: f"SUBSTR(CAST({q(x)} AS TEXT), 1, 10)") if k == "date" else (
                lambda x: f"CAST({q(x)} AS INTEGER)")
            for i, a in enumerate(cs[:6]):
                for b in cs[i + 1:6]:
                    r = db.rows(f"SELECT COUNT(*), SUM({val(a)} <> {val(b)}) FROM (SELECT * FROM "
                                f"{q(t)} LIMIT {SAMPLE}) WHERE {q(a)} IS NOT NULL AND {q(b)} IS NOT NULL")
                    if disagree(r):
                        pairs.append([a, b, r[0][1], r[0][0]])
        if pairs:
            sites.append({"kind": "lookalike_columns", "table": t, "columns": pairs[:4],
                          "strength": len(pairs)})
    for j in js:
        c, p = j["child"], j["parent"]
        if c == p:  # a self-join pairs different rows (an employee and their manager)
            continue
        ccols = {norm(x): x for x, _ in sch[c]}
        pcols = {norm(x): x for x, _ in sch[p]}
        pairs = []
        for k in sorted(set(ccols) & set(pcols)):
            a, b = ccols[k], pcols[k]
            if a in j["child_cols"] or b in j["parent_keys"] or IDENTITY.search(a):
                continue
            r = db.rows(f"SELECT COUNT(*), SUM(x.{q(a)} <> y.{q(b)}) FROM (SELECT * FROM {q(c)} "
                        f"LIMIT {SAMPLE}) x JOIN {q(p)} y ON {on(j)} "
                        f"WHERE x.{q(a)} IS NOT NULL AND y.{q(b)} IS NOT NULL")
            if disagree(r):
                pairs.append([f"{c}.{a}", f"{p}.{b}", r[0][1], r[0][0]])
        if pairs:
            sites.append({"kind": "lookalike_columns", "child": c, "parent": p,
                          "columns": pairs[:4], "strength": len(pairs),
                          "via": f"{keyref(c, j['child_cols'])} = {keyref(p, j['parent_keys'])}"})
    return sites


def orphan_sites(db: DB, js: list[dict]) -> list[dict]:
    sites = []
    for j in js:
        c, p, cc, pk = j["child"], j["parent"], j["child_cols"], j["parent_keys"]
        orphans = (f"FROM {q(c)} WHERE {not_null(cc)} AND ({qcols(cc)}) NOT IN "
                   f"(SELECT {qcols(pk)} FROM {q(p)} WHERE {not_null(pk)})")
        r = db.rows(f"SELECT COUNT(*) {orphans}")
        if r and r[0][0]:
            k = db.rows(f"SELECT COUNT(*) FROM (SELECT DISTINCT {qcols(cc)} {orphans})")
            sites.append({"kind": "orphan_rows", **j, "orphan_rows": r[0][0],
                          "orphan_keys": k[0][0] if k else None, "strength": r[0][0]})
    return sites


def name_pair_sites(db: DB, sch: dict, uniq: dict) -> list[dict]:
    """First and last name columns that together cover several IDs."""
    sites = []
    for t, cols in sch.items():
        names = [c for c, _ in cols]
        first = next((c for c in names if re.search(r"first", c, re.I) and NAMEY.search(c)
                      or re.fullmatch(r"(?i)f_?name|first", c)), None)
        last = next((c for c in names if re.search(r"last|sur", c, re.I) and NAMEY.search(c)
                     or re.fullmatch(r"(?i)l_?name|last", c)), None)
        for key in uniq.get(t, [])[:1]:
            if not first or not last:
                continue
            r = db.rows(f"SELECT {q(first)}, {q(last)}, COUNT(DISTINCT {q(key)}) AS k FROM {q(t)} "
                        f"WHERE {q(first)} IS NOT NULL AND {q(last)} IS NOT NULL GROUP BY 1, 2 "
                        f"HAVING k > 1 ORDER BY k DESC LIMIT 5")
            if r:
                sites.append({"kind": "shared_name", "table": t, "id_column": key,
                              "name_column": f"{first} + {last}",
                              "names_with_several_ids": len(r),
                              "examples": [[f"{a} {b}"[:60], k] for a, b, k in r], "strength": len(r)})
    return sites


def shared_name_sites(db: DB, sch: dict, prof: dict, uniq: dict) -> list[dict]:
    sites = name_pair_sites(db, sch, uniq)
    for t, cols in sch.items():
        for key in uniq.get(t, [])[:1]:
            for c, decl in cols:
                p = (prof.get(t) or {}).get(c) or {}
                if c == key or is_numeric(decl, p) or not NAMEY.search(c):
                    continue
                r = db.rows(f"SELECT {q(c)}, COUNT(DISTINCT {q(key)}) AS k FROM {q(t)} "
                            f"WHERE {q(c)} IS NOT NULL GROUP BY {q(c)} HAVING k > 1 "
                            f"ORDER BY k DESC LIMIT 5")
                if r:
                    n = db.rows(f"SELECT COUNT(*) FROM (SELECT {q(c)} FROM {q(t)} GROUP BY "
                                f"{q(c)} HAVING COUNT(DISTINCT {q(key)}) > 1)")
                    sites.append({"kind": "shared_name", "table": t, "id_column": key,
                                  "name_column": c, "names_with_several_ids": n[0][0] if n else None,
                                  "examples": [[str(v)[:60], k] for v, k in r],
                                  "strength": n[0][0] if n else 1})
    return sites


def null_zero_sites(db: DB, sch: dict, prof: dict, uniq: dict) -> list[dict]:
    sites = []
    for t, cols in sch.items():
        for c, decl in cols:
            p = (prof.get(t) or {}).get(c) or {}
            if c in uniq.get(t, []) or re.search(r"id$", c, re.I) or not is_numeric(decl, p):
                continue
            r = db.rows(f"SELECT COUNT(*), COUNT({q(c)}), SUM({q(c)} = 0), "
                        f"COUNT(DISTINCT {q(c)}) FROM {q(t)}")
            if not r or not r[0][0] or r[0][3] <= 2:  # skip empty and 0/1 flag columns
                continue
            n, nonnull, zeros = r[0][0], r[0][1], r[0][2] or 0
            nulls = n - nonnull
            if (0.01 <= nulls / n <= 0.95) or zeros:
                share = max(nulls, zeros) / n
                sites.append({"kind": "null_or_zero", "table": t, "column": c, "rows": n,
                              "nulls": nulls, "zeros": zeros,
                              "strength": round(min(share, 1 - share), 3)})  # mixed is best
    return sites


def overlapping_sites(db: DB, sch: dict, prof: dict) -> list[dict]:
    sites = []
    for t, cols in sch.items():
        for c, decl in cols:
            p = (prof.get(t) or {}).get(c) or {}
            if is_numeric(decl, p):
                continue
            vals = [v for v, _ in p.get("values") or []]
            if not vals:
                r = db.rows(f"SELECT DISTINCT {q(c)} FROM {q(t)} WHERE {q(c)} IS NOT NULL LIMIT 201")
                vals = [str(x[0]) for x in r or []]
            if not 2 <= len(vals) <= 200:  # categories and job titles, not free text
                continue
            pairs = []
            for a in vals:
                for b in vals:
                    if a == b:
                        continue
                    la, lb = a.strip().lower(), b.strip().lower()
                    if (la == lb and a < b) or (len(la) >= 3 and la != lb and la in lb):
                        pairs.append([a, b])
            if pairs:
                sites.append({"kind": "overlapping", "table": t, "column": c,
                              "n_values": len(vals), "pairs": pairs[:6], "strength": len(pairs)})
    return sites


def mixed_date_sites(prof: dict) -> list[dict]:
    sites = []
    for t, cols in prof.items():
        for c, p in cols.items():
            shapes = [(s, share, ex) for s, share, ex in p.get("shapes") or []
                      if DATE_SHAPE.match(s) and share >= 0.02]
            if len({s for s, _, _ in shapes}) >= 2:
                sites.append({"kind": "mixed_dates", "table": t, "column": c,
                              "shapes": shapes, "strength": len(shapes)})
    return sites


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--datasources", help="comma-separated database names (default: all)")
    ap.add_argument("--budget-s", type=float, default=20.0, help="time limit per query")
    ap.add_argument("--per-kind", type=int, default=12, help="strongest sites kept per kind")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    want = set(args.datasources.split(",")) if args.datasources else None
    for path in sorted(SQLITE_DIR.glob("*.sqlite")):
        name = path.stem
        if want and name not in want:
            continue
        t0 = time.time()
        prof_path = DCE_PROJECT_DIR / "output" / "profile" / f"{name}.json"
        keys_path = DCE_PROJECT_DIR / "output" / "keys" / f"{name}.json"
        prof = {t: rec.get("columns") or {} for t, rec in
                (json.loads(prof_path.read_text()) if prof_path.exists() else {}).items()}
        keys = json.loads(keys_path.read_text()) if keys_path.exists() else {}
        db = DB(path, args.budget_s)
        sch = schema(db)
        uniq = unique_columns(db, sch, keys)
        js = joins(db, sch, uniq)
        sites = (fanout_sites(db, sch, prof, uniq, js) + shared_name_sites(db, sch, prof, uniq)
                 + null_zero_sites(db, sch, prof, uniq) + overlapping_sites(db, sch, prof)
                 + mixed_date_sites(prof) + orphan_sites(db, js) + lookalike_sites(db, sch, prof, js))
        db.con.close()
        kept = []
        for kind in dict.fromkeys(s["kind"] for s in sites):
            kept += sorted((s for s in sites if s["kind"] == kind),
                           key=lambda s: -s["strength"])[:args.per_kind]
        (out / f"{name}.json").write_text(json.dumps({"db": name, "sites": kept}, indent=1,
                                                     default=str))
        counts = {k: sum(1 for s in kept if s["kind"] == k) for k in dict.fromkeys(
            s["kind"] for s in kept)}
        print(f"{name}: {counts} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
