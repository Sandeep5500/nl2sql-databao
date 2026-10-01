#!/usr/bin/env python3
"""Deterministic, SQL-verified enrichment for the DCE YAMLs (no LLM).

The LLM enrichment (enrich_dce.py) sees 5 physical rows per table and nothing
across tables, so it cannot know value distributions, table grain, join keys,
or which id is the coarser entity key -- and on e_commerce it got the
customer_id / customer_unique_id semantics backwards. This pass profiles the
SQLite databases directly and writes verified facts into the YAMLs:

  column  : "[Profile] ..."   rows, null %, distinct, full enum or top values,
                              range, date format of TEXT dates
  table   : "[Structure] ..." grain (smallest unique key), inferred joins with
                              value coverage, entity keys, similar tables
  foreign_keys : inferred joins added as `inferred_fk_*` (enforced: false)
  samples : 5 random rows instead of the first 5 physical rows

Descriptions cut off mid-sentence (256-token cap in the critique pass) are
trimmed to their last complete sentence. Re-running is idempotent: previous
[Profile]/[Structure] suffixes and inferred FKs are stripped first.

Reads only database contents and schema -- never questions or gold answers.

Then re-index (from spider2-dce/, embed server up):
    uv run --project ../nl2sql-v2 dce index

Usage (from spider2-dce/):
    python ../scripts/profile_dce.py                       # all datasources
    python ../scripts/profile_dce.py --only f1,e_commerce  # subset
    python ../scripts/profile_dce.py --db-dir <dir with *.sqlite>  # DBs not at config path
    python ../scripts/profile_dce.py --dry-run --only f1   # print, write nothing
"""

import argparse
import itertools
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

import yaml

PROFILE_TAG = " [Profile] "
STRUCT_TAG = " [Structure] "
INFERRED_PREFIX = "inferred_fk_"

ENUM_MAX = 30          # list every value when a column has at most this many
TOP_K = 8              # otherwise show the top-K most frequent values
VALUE_CHARS = 40
FREE_TEXT_LEN = 60     # skip value lists for columns whose values are longer
COVERAGE_MIN = 0.9     # share of child values that must exist in the parent
GRAIN_MAX_COLS = 4
GRAIN_CANDIDATES = 8

DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$"), "YYYY-MM-DD HH:MM:SS"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"), "ISO YYYY-MM-DDTHH:MM"),
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "YYYY-MM-DD"),
    (re.compile(r"^\d{4}-\d{2}$"), "YYYY-MM"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "D/M/YYYY or M/D/YYYY"),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), "D-M-YYYY or M-D-YYYY"),
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"), "YYYY/MM/DD"),
    (re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$"), "time H:MM[:SS]"),
]
TERMINAL = (".", "!", "?", '"', "'", ")", "]", "`")


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


ID_RX = re.compile(r"(^id$|_id$|_key$|[a-z0-9](Id|ID)$|^(id|ID)_|^[A-Z]{1,3}ID$)")   # ^[A-Z]ID: MID, PID


TABLE_STEMS = set()   # singular/plural forms of the current datasource's table names


def is_idlike_strict(col):
    # `grid`, `paid`, `valid` are not ids; `CustomerID`, `customerId`, `cust_id`, `id` are,
    # and so is lowercase `categoryid` when `category` names a table (northwind)
    n = col.lower()
    if ID_RX.search(col) is not None or n == "id" or n.endswith(("_id", "_key")):
        return True
    return n.endswith("id") and n[:-2] in TABLE_STEMS


def short(v):
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    s = str(v)
    return s if len(s) <= VALUE_CHARS else s[:VALUE_CHARS] + "..."


def fmt_num(x):
    if isinstance(x, float):
        return f"{x:.4g}" if abs(x) < 1e6 else f"{x:.6g}"
    return str(x)


def singular_forms(name):
    n = name.lower()
    forms = {n}
    if n.endswith("ies"):
        forms.add(n[:-3] + "y")
    if n.endswith("es"):
        forms.add(n[:-2])
    if n.endswith("s"):
        forms.add(n[:-1])
    return forms


# --------------------------------------------------------------------------- profiling

class DB:
    """Read-only connection; every query gets a time budget (sqlite3.OperationalError on overrun)."""

    def __init__(self, path, query_seconds=30):
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.conn.text_factory = lambda b: b.decode("utf-8", "replace")
        self.query_seconds = query_seconds
        self.deadline = None
        self.conn.set_progress_handler(
            lambda: 1 if self.deadline and time.time() > self.deadline else 0, 20000)

    def _fetch(self, sql, args, seconds, many):
        self.deadline = time.time() + (seconds or self.query_seconds)
        try:
            cur = self.conn.execute(sql, args)
            return cur.fetchall() if many else cur.fetchone()
        finally:
            self.deadline = None

    def one(self, sql, args=(), seconds=None):
        return self._fetch(sql, args, seconds, False)

    def all(self, sql, args=(), seconds=None):
        return self._fetch(sql, args, seconds, True)

    def materialize_view(self, name, max_rows):
        """Shadow a view with a same-named TEMP table (temp resolves before main), so
        profiling queries do not recompute the view every time."""
        self.deadline = time.time() + 5 * self.query_seconds
        try:
            self.conn.execute(f"CREATE TEMP TABLE {q(name)} AS SELECT * FROM main.{q(name)} LIMIT {int(max_rows)}")
            return True
        except sqlite3.Error as e:
            print(f"    could not materialize view {name}: {e}")
            return False
        finally:
            self.deadline = None


def profile_column(db, table, col, nrows):
    t, c = q(table), q(col)
    cnt, distinct, mn, mx, maxlen, ntext = db.one(
        f"SELECT COUNT({c}), COUNT(DISTINCT {c}), MIN({c}), MAX({c}), "
        f"MAX(LENGTH({c})), SUM(typeof({c}) = 'text') FROM {t}")
    p = {"rows": nrows, "non_null": cnt, "distinct": distinct,
         "null_pct": 0.0 if not nrows else round(100 * (nrows - cnt) / nrows, 1),
         "min": mn, "max": mx, "max_len": maxlen or 0, "text_share": (ntext or 0) / cnt if cnt else 0}
    p["unique"] = bool(cnt) and distinct == cnt
    p["values"], p["complete_values"] = [], False
    if cnt and (maxlen or 0) <= FREE_TEXT_LEN and not (p["unique"] and distinct > ENUM_MAX)             and not (is_idlike_strict(col) and distinct > ENUM_MAX):
        rows = db.all(f"SELECT {c}, COUNT(*) n FROM {t} WHERE {c} IS NOT NULL "
                      f"GROUP BY {c} ORDER BY n DESC, {c} LIMIT ?", (ENUM_MAX if distinct <= ENUM_MAX else TOP_K,))
        p["values"] = [(short(v), n) for v, n in rows]
        p["complete_values"] = distinct <= ENUM_MAX
    p["date_format"] = None
    if cnt and p["text_share"] > 0.9:
        vals = [r[0] for r in db.all(f"SELECT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT 200")]
        for rx, label in DATE_PATTERNS:
            hits = sum(1 for v in vals if isinstance(v, str) and rx.match(v.strip()))
            if vals and hits / len(vals) >= 0.9:
                p["date_format"] = label
                break
    return p


def column_profile_text(p):
    if p["rows"] == 0:
        return "table is empty."
    bits = [f"{p['null_pct']:g}% null" if p["null_pct"] else "never null",
            f"{p['distinct']} distinct" + (" (unique per row)" if p["unique"] else "")]
    if p["date_format"]:
        bits.append(f"dates stored as TEXT in format {p['date_format']}, range {short(p['min'])} to {short(p['max'])}")
    if p["values"] and not (p["date_format"] and not p["complete_values"]):
        vals = ", ".join(f"{v} ({n})" for v, n in p["values"])
        bits.append(("all values: " if p["complete_values"] else "most frequent: ") + vals)
    elif p["min"] is not None and not p["date_format"] and isinstance(p["min"], (int, float)):
        bits.append(f"range {fmt_num(p['min'])} to {fmt_num(p['max'])}")
    return "; ".join(bits) + "."


# --------------------------------------------------------------------------- structure

def is_unique_set(db, table, cols):
    t = q(table)
    g = ", ".join(q(c) for c in cols)
    notnull = " AND ".join(f"{q(c)} IS NOT NULL" for c in cols)
    try:
        dup = db.one(f"SELECT 1 FROM {t} WHERE {notnull} GROUP BY {g} HAVING COUNT(*) > 1 LIMIT 1")
        nulls = db.one(f"SELECT 1 FROM {t} WHERE NOT ({notnull}) LIMIT 1")
    except sqlite3.Error:
        return False   # over the time budget: treat as not proven unique
    return dup is None and nulls is None


def find_grain(db, table, tinfo, profiles, nrows):
    """Smallest set of key-like columns that is unique per row."""
    if nrows == 0:
        return None
    pk = (tinfo.get("primary_key") or {}).get("columns") or []
    if pk and is_unique_set(db, table, pk):
        return list(pk)
    # pandas' leftover `index` / `level_0` columns are row numbers, not a grain
    cols = [c["name"] for c in tinfo.get("columns", []) if c["name"] in profiles
            and c["name"].lower() not in ("index", "level_0")]
    singles = [c for c in cols if profiles[c]["unique"] and profiles[c]["null_pct"] == 0]
    id_singles = [c for c in singles if is_idlike_strict(c)]
    if id_singles:
        return [id_singles[0]]
    return composite_key(db, table, cols, profiles, nrows) or singles[:1] or None


def is_surrogate(table, grain):
    """Single-column own-id key (constructor_standings_id, id, result_id on results)."""
    if not grain or len(grain) != 1:
        return False
    c = grain[0].lower()
    stem = re.sub(r"(_id|id)$", "", c)
    return c == "id" or table_matches_stem(stem, table) or c.replace("_id", "") in table.lower()


def natural_grain(db, table, tinfo, profiles, nrows, grain):
    """For a surrogate-keyed table, the business key it actually repeats on
    (constructor_standings: race_id x constructor_id)."""
    if nrows == 0 or not is_surrogate(table, grain):
        return None
    cols = [c["name"] for c in tinfo.get("columns", []) if c["name"] in profiles and c["name"] != grain[0]]
    return composite_key(db, table, cols, profiles, nrows)


def composite_key(db, table, cols, profiles, nrows):
    cand = [c for c in cols if is_idlike_strict(c) and profiles[c]["null_pct"] == 0 and profiles[c]["distinct"] > 1]
    # also allow low-cardinality non-float discriminators (e.g. lap, year, position)
    extra = [c for c in cols if c not in cand and profiles[c]["null_pct"] == 0
             and not isinstance(profiles[c]["min"], float) and 1 < profiles[c]["distinct"] < nrows
             and profiles[c]["max_len"] <= 30]
    cand = sorted(cand, key=lambda c: -profiles[c]["distinct"])[:GRAIN_CANDIDATES]
    extra = sorted(extra, key=lambda c: -profiles[c]["distinct"])[:4]
    pool = cand + extra
    for k in range(2, GRAIN_MAX_COLS + 1):
        for combo in itertools.combinations(pool, k):
            if sum(1 for c in combo if c in cand) == 0:
                continue
            prod = 1
            for c in combo:
                prod *= max(profiles[c]["distinct"], 1)
            if prod < nrows:
                continue
            if is_unique_set(db, table, combo):
                return list(combo)
    return None


def table_matches_stem(stem, table):
    tl = table.lower()
    parts = tl.split("_")
    cands = {tl, parts[-1], "_".join(parts[1:]) if len(parts) > 1 else tl}
    forms = set()
    for c in cands:
        forms |= singular_forms(c)
    return stem.lower() in forms


ROLE_COVERAGE_MIN = 0.95
KEY_TOKENS = {"id", "key", "code", "ref", "fk", "no", "num"}
# role words that point at a person table whatever the column is called
PERSON_ROLES = {"manager", "supervisor", "reports", "reportsto", "boss", "chair", "rep",
                "head", "lead", "mentor", "owner", "author"}
PERSON_TABLES = {"employee", "employees", "staff", "person", "people", "user", "users",
                 "member", "members", "faculty"}


def name_tokens(col):
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", col)
    return {p.lower() for p in parts if not p.isdigit()} - KEY_TOKENS


def role_named_joins(db, child, tables, grains, profiles, declared, found):
    """FKs whose names do not match their target (ktx's value-evidence layer, name-light):
    match.away_player_1 -> player, film.original_language_id -> language,
    store.manager_staff_id -> staff, employees.reportsto -> employees.
    A column token must name the parent table (or be a person role pointing at a person
    table); the SQL coverage check then has to pass at a stricter threshold."""
    done = {c for j in found if j["child"] == child for c in j["cols"]}
    done |= {c for t, cs, _ in declared if t == child for c in cs}
    out = []
    for col, p in profiles[child].items():
        if col in done or not p["non_null"] or p["distinct"] < 3 or p["date_format"] \
                or isinstance(p["min"], float) or grains.get(child) == [col]:
            continue
        toks = name_tokens(col)
        if not toks:
            continue
        best = None
        for parent in tables:
            # any unique id column can be the target (match.away_player_1 -> player.player_api_id)
            pkeys = [k for k, pk in profiles[parent].items()
                     if pk["unique"] and pk["null_pct"] == 0 and is_idlike_strict(k)]
            if not pkeys:
                continue
            pforms = set()
            for part in re.split(r"[_\s]+", parent.lower()):
                pforms |= singular_forms(part)
            named = bool(toks & pforms)
            role = bool(toks & PERSON_ROLES) and bool(pforms & PERSON_TABLES)
            if not (named or role):
                continue
            if (child, (col,), parent) in declared:
                break
            if parent == child and p["unique"]:
                continue   # a unique column is the table's own alternate key, not a self-reference
            for key in pkeys:
                pk = profiles[parent][key]
                # small integers (durations, strengths, pitch coordinates) fall inside any id
                # range; real FK values spread over a good part of the parent's key range
                if isinstance(p["max"], int) and isinstance(pk["max"], int) and pk["max"] > 0                         and p["max"] < 0.2 * pk["max"]:
                    continue
                cov = coverage(db, child, [col], parent, [key])
                if cov is not None and cov >= ROLE_COVERAGE_MIN and (best is None or cov > best["coverage"]):
                    best = {"child": child, "cols": [col], "parent": parent, "keys": [key],
                            "coverage": cov, "card": "1:1" if p["unique"] else "N:1", "role_named": True}
        if best:
            out.append(best)
    return out


def infer_joins(db, tables, grains, profiles, declared):
    """Child column(s) -> parent key where >= COVERAGE_MIN of child values exist in the parent."""
    joins = []
    single_keys = {}   # table -> {col: True} for single-column unique keys
    for t in tables:
        keys = {c for c in profiles[t] if profiles[t][c]["unique"] and profiles[t][c]["null_pct"] < 50}
        single_keys[t] = keys
    for child in tables:
        for col, p in profiles[child].items():
            if not p["non_null"] or not is_idlike_strict(col):
                continue
            stem = re.sub(r"(_id|_key|_code|_ref|id)$", "", col, flags=re.I)
            # a table's own key is not a foreign key (country.id, classes.classid)
            if col.lower() == "id" or (grains.get(child) == [col] and stem and table_matches_stem(stem, child)):
                continue
            for parent in tables:
                if parent == child:
                    continue
                for key in single_keys[parent]:
                    name_match = key.lower() == col.lower()
                    stem_match = key.lower() in ("id", f"{stem.lower()}_id", f"{stem.lower()}id") \
                        and stem and table_matches_stem(stem, parent)
                    if not (name_match or stem_match):
                        continue
                    if (child, (col,), parent) in declared:
                        continue
                    # the child being the parent's own key (1:1 on same name between two keyed tables):
                    # keep, but only if coverage holds
                    cov = coverage(db, child, [col], parent, [key])
                    if cov is None or cov < COVERAGE_MIN:
                        continue
                    card = "1:1" if p["unique"] else "N:1"
                    joins.append({"child": child, "cols": [col], "parent": parent, "keys": [key],
                                  "coverage": cov, "card": card})
        joins.extend(role_named_joins(db, child, tables, grains, profiles, declared, joins))
        # composite: parent grain with several columns all present in child
        ccols = {c.lower(): c for c in profiles[child]}
        for parent in tables:
            g = grains.get(parent)
            if parent == child or not g or len(g) < 2:
                continue
            if all(k.lower() in ccols for k in g):
                cols = [ccols[k.lower()] for k in g]
                if grains.get(child) and sorted(x.lower() for x in grains[child]) == sorted(x.lower() for x in g):
                    card = "1:1"
                else:
                    card = "N:1"
                if (child, tuple(cols), parent) in declared:
                    continue
                cov = coverage(db, child, cols, parent, g)
                if cov is not None and cov >= COVERAGE_MIN:
                    joins.append({"child": child, "cols": cols, "parent": parent, "keys": list(g),
                                  "coverage": cov, "card": card})
    # a 2-column composite parent that many tables "join" to is a derived/stats table keyed on
    # common dimensions (driver_standings_ext on race_id+driver_id): noise, drop it
    hub = {}
    for j in joins:
        if len(j["cols"]) == 2:
            hub[j["parent"]] = hub.get(j["parent"], 0) + 1
    joins = [j for j in joins if len(j["cols"]) != 2 or hub[j["parent"]] <= 2]
    # prefer, per child column, the parent whose name matches the stem (drop same-name siblings
    # that are only unique by accident when a stem-matching parent exists)
    by_col = {}
    for j in joins:
        if len(j["cols"]) == 1:
            by_col.setdefault((j["child"], j["cols"][0]), []).append(j)
    keep = [j for j in joins if len(j["cols"]) > 1]
    for (child, col), js in by_col.items():
        stem = re.sub(r"(_id|_key|_code|_ref|id)$", "", col, flags=re.I)
        preferred = [j for j in js if stem and table_matches_stem(stem, j["parent"])]
        keep.extend(preferred or js)
    # a 1:1 link found in both directions: keep the one pointing at the stem-named table
    sig = {(j["child"], tuple(j["cols"]), j["parent"], tuple(j["keys"])) for j in keep}
    out = []
    for j in keep:
        rev = (j["parent"], tuple(j["keys"]), j["child"], tuple(j["cols"]))
        if j["card"] == "1:1" and rev in sig:
            stem = re.sub(r"(_id|_key|_code|_ref|id)$", "", j["cols"][0], flags=re.I)
            fwd_ok = bool(stem) and table_matches_stem(stem, j["parent"])
            rev_ok = bool(stem) and table_matches_stem(stem, j["child"])
            if rev_ok and not fwd_ok or (fwd_ok == rev_ok and j["child"] > j["parent"]):
                continue
        out.append(j)
    return out


def coverage(db, child, ccols, parent, pcols):
    # set-based (EXCEPT sorts once) -- a correlated NOT EXISTS is quadratic on unindexed keys
    ct, pt = q(child), q(parent)
    notnull = " AND ".join(f"{q(c)} IS NOT NULL" for c in ccols)
    cg = ", ".join(q(c) for c in ccols)
    pg = ", ".join(q(c) for c in pcols)
    child_set = f"SELECT DISTINCT {cg} FROM {ct} WHERE {notnull}"
    try:
        total = db.one(f"SELECT COUNT(*) FROM ({child_set})")[0]
        orphans = db.one(f"SELECT COUNT(*) FROM ({child_set} EXCEPT SELECT {pg} FROM {pt})")[0]
    except sqlite3.Error:
        return None
    if not total:
        return None
    return round(1 - (orphans or 0) / total, 3)


def entity_keys(db, table, grain, profiles, join_children):
    """Id-like column `a` that groups the table's unique key `b` and has no table of its own
    (e.g. customer_unique_id groups customer_id): the person/entity-level identifier."""
    out = []
    if not grain or len(grain) != 1:
        return out
    b = grain[0]
    for a, pa in profiles.items():
        if a == b or not is_idlike_strict(a) or (table, a) in join_children:
            continue
        # mostly-null alternate ids (legislators.id_thomas) only look coarse because of their NULLs
        if pa["null_pct"] > 0 or not pa["non_null"] or pa["distinct"] < 10 or pa["distinct"] >= 0.98 * profiles[b]["distinct"]:
            continue
        # a must be a pure grouping of b: each b has one a (trivially true when b is unique),
        # and a must be a real many-to-one grouping
        ratio = profiles[b]["distinct"] / pa["distinct"]
        out.append({"coarse": a, "fine": b, "ratio": round(ratio, 2)})
    return out


def similar_tables(tables, grains, nrows):
    groups = {}
    for t in tables:
        parts = t.lower().split("_")
        if len(parts) < 2:
            continue
        groups.setdefault(("last", parts[-1]), set()).add(t)
        groups.setdefault(("first", parts[0]), set()).add(t)
        if len(parts) >= 3:
            groups.setdefault(("first2", "_".join(parts[:2])), set()).add(t)
    sims = {t: set() for t in tables}
    for members in groups.values():
        if 2 <= len(members) <= 6 and len(members) < len(tables):
            for t in members:
                sims[t] |= members - {t}
    return sims


# --------------------------------------------------------------------------- description edits

def strip_tags(text, tag):
    text = text or ""
    i = text.find(tag.strip())
    return text[:i].rstrip() if i >= 0 else text.rstrip()


def fix_truncated(text):
    text = (text or "").strip()
    if not text or text.endswith(TERMINAL):
        return text, False
    cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
    if cut > 0:
        return text[:cut + 1], True
    return text + "...", True


SPECULATION = re.compile(r"(often|may|might|likely|possibly|typically|probably|external systems?|"
                         r"data integration|for different purposes)", re.I)


def drop_sentences_matching(text, rx):
    sents = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(x for x in sents if not rx.search(x))


def drop_sentences_mentioning(text, names):
    sents = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sents if not any(re.search(rf"\b{re.escape(n)}\b", s) for n in names)]
    return " ".join(kept) if kept else ""


# --------------------------------------------------------------------------- main per datasource

def process(src_cfg, out_yaml, db_dir, dry_run, backup_dir, profile_dir, query_seconds=30, view_rows=200000):
    cfg = yaml.safe_load(src_cfg.read_text(encoding="utf-8"))
    db_path = Path(cfg["connection"]["database_path"])
    if db_dir:
        db_path = Path(db_dir) / db_path.name
    if not db_path.exists():
        print(f"  SKIP {src_cfg.stem}: {db_path} not found")
        return None
    doc = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    schema = doc["context"]["catalogs"][0]["schemas"][0]
    tinfos = {t["name"]: t for t in schema["tables"]}
    db = DB(db_path, query_seconds)
    kinds = dict(db.all("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')"))
    tables = [t for t in tinfos if t in kinds]
    TABLE_STEMS.clear()
    for t in tables:
        for part in {t, t.split("_")[-1]}:
            TABLE_STEMS.update(singular_forms(part))
    # views too expensive to materialize are left untouched
    tables = [t for t in tables if kinds[t] != "view" or db.materialize_view(t, view_rows)]

    t0 = time.time()
    nrows, profiles, grains, naturals = {}, {}, {}, {}
    for t in tables:
        try:
            nrows[t] = db.one(f"SELECT COUNT(*) FROM {q(t)}")[0]
        except sqlite3.Error as e:
            print(f"    count failed {t}: {e}")
            nrows[t] = 0
        profiles[t] = {}
        for c in tinfos[t].get("columns", []):
            try:
                profiles[t][c["name"]] = profile_column(db, t, c["name"], nrows[t])
            except sqlite3.Error as e:
                print(f"    profile failed {t}.{c['name']}: {e}")
        try:
            grains[t] = find_grain(db, t, tinfos[t], profiles[t], nrows[t])
            naturals[t] = natural_grain(db, t, tinfos[t], profiles[t], nrows[t], grains[t])
        except sqlite3.Error as e:
            print(f"    grain failed {t}: {e}")
            grains[t] = None
            naturals[t] = None

    declared = set()
    for t in tables:
        for fk in tinfos[t].get("foreign_keys") or []:
            if str(fk.get("name", "")).startswith(INFERRED_PREFIX):
                continue
            ref = str(fk.get("referenced_table", "")).split(".")[-1]
            cols = tuple(m["from_column"] for m in fk.get("mapping", []))
            declared.add((t, cols, ref))
    joins = infer_joins(db, tables, grains, profiles, declared)
    join_children = {(j["child"], c) for j in joins for c in j["cols"]} | {(t, c) for t, cs, _ in declared for c in cs}
    ents = {t: entity_keys(db, t, grains[t], profiles[t], join_children) for t in tables}
    sims = similar_tables(tables, grains, nrows)

    n_trunc = 0
    for t in tables:
        ti = tinfos[t]
        ent_cols = {e["coarse"]: e for e in ents[t]}
        ent_fine = {e["fine"]: e for e in ents[t]}
        for c in ti.get("columns", []):
            name = c["name"]
            p = profiles[t].get(name)
            base = strip_tags(c.get("description"), PROFILE_TAG)
            base, was_trunc = fix_truncated(base)
            n_trunc += was_trunc
            facts = []
            if is_idlike_strict(name):
                # hedged guesses about what an id is "used for" are the critique pass's inventions
                base = drop_sentences_matching(base, SPECULATION)
            if name in ent_cols or name in ent_fine:
                # the LLM's cross-column claims about ids are unverified (and wrong on e_commerce)
                others = [e["fine"] for e in ents[t] if e["coarse"] == name] + \
                         [e["coarse"] for e in ents[t] if e["fine"] == name]
                base = drop_sentences_mentioning(base, others)
            if name in ent_cols:
                e = ent_cols[name]
                facts.append(f"COARSER KEY than {e['fine']}: one {name} covers about {e['ratio']:g} {e['fine']} "
                             f"values; when the question counts or groups the thing {name} identifies, "
                             f"use {name}, not {e['fine']}")
            if name in ent_fine:
                e = ent_fine[name]
                facts.append(f"row-level key; several {name} values can belong to one {e['coarse']}")
            for j in joins:
                if j["child"] == t and name in j["cols"]:
                    tgt = ", ".join(f"{j['parent']}.{k}" for k in j["keys"])
                    facts.append(f"joins to {tgt} ({j['card']}, {j['coverage']:.0%} of values match)"
                                 + (" as part of a composite key" if len(j["cols"]) > 1 else ""))
            if p:
                facts.append(column_profile_text(p).rstrip("."))
            c["description"] = (base + PROFILE_TAG + "; ".join(facts) + ".").strip()

        # table description
        tbase = strip_tags(ti.get("description"), STRUCT_TAG)
        tbase, was_trunc = fix_truncated(tbase)
        n_trunc += was_trunc
        s = [f"{nrows[t]} rows."]
        g = grains[t]
        nat = naturals.get(t)
        s.append(f"Grain: one row per ({', '.join(nat)}); {g[0]} is a surrogate row id." if nat else
                 f"Grain: one row per ({', '.join(g)})." if g else
                 "Grain: no unique key among its id columns; rows can repeat.")
        out_j = [j for j in joins if j["child"] == t]
        if out_j:
            s.append("Joins: " + "; ".join(
                (f"({', '.join(j['cols'])}) -> {j['parent']}({', '.join(j['keys'])}) join on ALL these columns"
                 if len(j["cols"]) > 1 else f"{j['cols'][0]} -> {j['parent']}.{j['keys'][0]}")
                + f" [{j['card']}, {j['coverage']:.0%}]" for j in out_j) + ".")
        in_j = [j for j in joins if j["parent"] == t]
        if in_j:
            s.append("Referenced by: " + ", ".join(sorted({f"{j['child']}.{'+'.join(j['cols'])}" for j in in_j})) + ".")
        for e in ents[t]:
            s.append(f"Coarser key: {e['coarse']} groups {e['fine']} (~{e['ratio']:g} per value); "
                     f"count/group by {e['coarse']} for {e['coarse']}-level answers.")
        if sims[t]:
            s.append("Similar tables (check which fits the question): " + "; ".join(
                f"{o} (grain {', '.join(grains.get(o) or ['none'])}, {nrows.get(o, '?')} rows)"
                for o in sorted(sims[t])) + ".")
        if ti.get("kind") == "view":
            s.append("This is a VIEW derived from other tables.")
        ti["description"] = (tbase + STRUCT_TAG + " ".join(s)).strip()

        # structural inferred FKs
        fks = [fk for fk in (ti.get("foreign_keys") or []) if not str(fk.get("name", "")).startswith(INFERRED_PREFIX)]
        for i, j in enumerate(out_j):
            fks.append({"name": f"{INFERRED_PREFIX}{t}_{i}",
                        "mapping": [{"from_column": c, "to_column": k} for c, k in zip(j["cols"], j["keys"])],
                        "referenced_table": f"main.{j['parent']}", "enforced": False, "validated": False,
                        "on_update": "no action", "on_delete": "no action"})
        if fks:
            ti["foreign_keys"] = fks
        elif "foreign_keys" in ti:
            ti["foreign_keys"] = []

        # representative samples
        if ti.get("samples") is not None and nrows[t]:
            cols = [c["name"] for c in ti.get("columns", [])]
            try:
                rows = db.all(f"SELECT {', '.join(q(c) for c in cols)} FROM {q(t)} ORDER BY RANDOM() LIMIT 5")
                ti["samples"] = [{c: (v if not isinstance(v, str) or len(v) <= 256 else v[:256]) for c, v in zip(cols, r)}
                                 for r in rows]
            except sqlite3.Error:
                pass

    summary = {"datasource": src_cfg.stem, "tables": len(tables), "seconds": round(time.time() - t0, 1),
               "grains_found": sum(1 for t in tables if grains[t]), "inferred_joins": len(joins),
               "declared_fks": len(declared), "entity_keys": sum(len(v) for v in ents.values()),
               "truncations_fixed": n_trunc}
    sidecar = {"summary": summary, "grains": grains, "natural_grains": naturals, "joins": joins, "entity_keys": ents,
               "similar": {t: sorted(v) for t, v in sims.items()},
               "profiles": {t: {c: {k: v for k, v in p.items()} for c, p in cs.items()} for t, cs in profiles.items()}}
    if dry_run:
        print(json.dumps({k: sidecar[k] for k in ("summary", "grains", "joins", "entity_keys")}, indent=1, default=str))
        return summary
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_yaml, backup_dir / out_yaml.name)
    out_yaml.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{src_cfg.stem}.json").write_text(json.dumps(sidecar, indent=1, default=str), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dce-dir", default=".", help="spider2-dce project dir")
    ap.add_argument("--db-dir", help="directory holding the .sqlite files (overrides config paths)")
    ap.add_argument("--only", help="comma-separated datasource names, e.g. f1,e_commerce")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--query-seconds", type=int, default=30, help="time budget per SQL query")
    ap.add_argument("--view-rows", type=int, default=200000, help="rows of each view materialized for profiling")
    args = ap.parse_args()

    dce = Path(args.dce_dir)
    src_dir, out_dir = dce / "src" / "databases", dce / "output" / "databases"
    # keep both OUT of output/: DCE indexes every folder of YAMLs it finds under output/
    backup_dir = dce / "backups" / f"databases_pre_profile_{time.strftime('%Y%m%d_%H%M%S')}"
    profile_dir = dce / "profiles"
    only = set(args.only.split(",")) if args.only else None
    results = []
    for cfg in sorted(src_dir.glob("*.yaml")):
        if only and cfg.stem not in only:
            continue
        out = out_dir / cfg.name
        if not out.exists():
            print(f"  SKIP {cfg.stem}: no built context at {out}")
            continue
        print(f"== {cfg.stem}")
        r = process(cfg, out, args.db_dir, args.dry_run, backup_dir, profile_dir,
                    args.query_seconds, args.view_rows)
        if r:
            print(f"   {r}")
            results.append(r)
    if results and not args.dry_run:
        print(f"\nbacked up originals to {backup_dir}\nprofiles in {profile_dir}")


if __name__ == "__main__":
    main()
