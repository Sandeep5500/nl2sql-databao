#!/usr/bin/env python3
"""Build a retrieval index for the spider2-lite warehouse databases.

    uv run python scripts/build_bq_context.py --source spider2_lite_bq --all
    uv run python scripts/build_bq_context.py --db ga360 --no-embed   # inspect first

Why this is cheap. The DCE pipeline for the SQLite databases is: connect, introspect,
then have an LLM write a description for every table and column, then embed. The LLM
step is the expensive one, and it exists because SQLite ships no descriptions at all.

BigQuery is the opposite case: spider2-lite already ships the whole catalog as JSON
*with the dataset publishers' own descriptions*, e.g.

    smid  INT64  -- FK to SMID in ACTIVITY_SMID.
    standard_value  FLOAT64  -- Standardised form of the VALUE

So the enriched artifact is synthesised straight from the catalog -- no warehouse
query, no LLM call, no credentials -- and only the embedding index has to be built.

Two things this does beyond reformatting:

  * Date-sharded families (ga_sessions_20160801, ...) collapse to one `ga_sessions_*`
    entry. ga360/ga4/firebase are where the 300-table databases come from, and
    hundreds of near-identical chunks would otherwise dominate every retrieval.

  * Foreign keys are recovered from the description prose ("FK to SMID in
    ACTIVITY_SMID"), accepted only when the named table actually exists in the
    catalog. These feed SearchContext._neighbours' join-hop listing, which is the
    signal the team's verified-keys work added on the SQLite side.

Output, per database, next to each other so CatalogSearchContext finds both:

    <out>/<db>.yaml   the enriched catalog, in the DCE output format
    <out>/<db>.npz    chunks + normalised vectors + the model and query prefix
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from nl2sql.config import DATA_SOURCES, SPIDER2_LITE
from nl2sql.lite_catalog import LiteCatalog

# nomic-embed-text v1.5 is what the SQLite index uses, and it is trained with task
# prefixes: documents and queries go into different sub-spaces without them. An index
# built with one convention must be queried with the same one, so both strings are
# written into the .npz rather than assumed.
EMBED_MODEL = "nomic-ai/nomic-embed-text-v1.5"
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

SHARD_SUFFIX = re.compile(r"^(?P<stem>.+?)_(?P<date>\d{6}(?:\d{2})?)$")

# "FK to SMID in ACTIVITY_SMID", "foreign key to patents.publications",
# "references assay.assay_id". Deliberately narrow, and every hit is then checked
# against the real table list -- a wrong join hint is worse than none.
FK_PATTERNS = [
    re.compile(r"\bFK\s+to\s+(?P<col>[\w.]+)\s+in\s+(?P<table>[\w.]+)", re.I),
    re.compile(r"\bforeign\s+key\s+(?:column\s+)?(?:to|into|of)\s+(?P<table>[\w.]+)"
               r"(?:\.(?P<col>\w+))?", re.I),
    re.compile(r"\breferences\s+(?P<table>[\w.]+)(?:\.(?P<col>\w+))?", re.I),
]


def collapse_shards(names: list[str]) -> tuple[list[str], dict]:
    """Same rule as run_benchmark.collapse_shards, on fully-qualified names."""
    fams = {}
    for n in names:
        m = SHARD_SUFFIX.match(n)
        if m:
            fams.setdefault(m.group("stem"), []).append(m.group("date"))
    families, drop = {}, set()
    for stem, dates in fams.items():
        if len(dates) < 3:
            continue
        families[f"{stem}_*"] = {"stem": stem, "shards": len(dates),
                                 "first": min(dates), "last": max(dates)}
        drop |= {f"{stem}_{d}" for d in dates}
    kept = [n for n in names if n not in drop]
    return sorted(kept + list(families)), families


def find_fks(table: str, col: str, desc: str, by_bare: dict) -> list[dict]:
    """Foreign keys stated in a column's description, kept only if resolvable."""
    out = []
    for pat in FK_PATTERNS:
        for m in pat.finditer(desc or ""):
            raw = m.group("table")
            target = by_bare.get(raw.lower()) or by_bare.get(
                raw.rsplit(".", 1)[-1].lower())
            if not target or target == table:
                continue
            to_col = (m.groupdict().get("col") or col)
            out.append({"name": f"prose_fk_{table.rsplit('.', 1)[-1]}_{col}",
                        "mapping": [{"from_column": col, "to_column": to_col}],
                        "referenced_table": target,
                        "enforced": False, "validated": False,
                        "source": "column description"})
            break
    return out


def build_tables(cat: LiteCatalog) -> tuple[list[dict], dict]:
    names, families = collapse_shards(cat.list_tables())
    by_bare = {n.rsplit(".", 1)[-1].lower(): n for n in names}
    tables = []
    for name in names:
        fam = families.get(name)
        probe = f"{fam['stem']}_{fam['last']}" if fam else name
        try:
            t = cat.table(probe)
        except Exception as e:
            tables.append({"name": name, "kind": "table",
                           "description": f"(catalog entry unreadable: {e})",
                           "columns": [], "samples": [], "foreign_keys": []})
            continue
        descs = t.descriptions or []
        cols, fks = [], []
        for i, (c, ty) in enumerate(t.columns):
            d = descs[i] if i < len(descs) else None
            cols.append({"name": c, "type": ty, "nullable": True,
                         "description": d or ""})
            fks += find_fks(name, c, d or "", by_bare)
        nested = [(pth, ty) for pth, ty in (t.nested or [])
                  if pth not in {c["name"] for c in cols}]
        desc = []
        if fam:
            desc.append(f"{fam['shards']} date-sharded tables, {fam['first']} to "
                        f"{fam['last']}; query as `{name}` and filter _TABLE_SUFFIX. "
                        f"All shards share this schema.")
        if nested:
            desc.append(f"Nested columns (use UNNEST / dotted paths): "
                        + ", ".join(f"{pth} {ty}" for pth, ty in nested[:40]))
        tables.append({
            "name": name, "kind": "table",
            "description": " ".join(desc),
            "columns": cols,
            "samples": (t.sample_rows or [])[:3],
            "foreign_keys": fks,
        })
    return tables, families


def chunk_texts(tables: list[dict]) -> list[str]:
    """Chunks in the shape SearchContext._chunk_table() parses.

    It yaml-loads each chunk and looks for a "table_name" key (a column chunk) or a
    dict under "table" (a table chunk), so these have to be real YAML with those
    keys -- not prose that merely mentions the table.
    """
    out = []
    for t in tables:
        out.append(yaml.safe_dump(
            {"table": {"name": t["name"], "description": t["description"],
                       "columns": [c["name"] for c in t["columns"]]}},
            sort_keys=False, allow_unicode=True, width=10_000))
        for c in t["columns"]:
            out.append(yaml.safe_dump(
                {"table_name": t["name"],
                 "column": {"name": c["name"], "type": c["type"],
                            "description": c["description"]}},
                sort_keys=False, allow_unicode=True, width=10_000))
    return out


def build_db(db_name: str, engine: str, out_dir: Path, embed: bool) -> dict:
    cat = LiteCatalog(db_name, engine, SPIDER2_LITE)
    if not cat.available:
        return {"db": db_name, "error": "no catalog directory"}
    raw = len(cat.list_tables())
    tables, families = build_tables(cat)
    doc = {
        "datasource_id": f"{engine}/{db_name}.yaml",
        "datasource_type": engine,
        "context": {"catalogs": [{
            "name": db_name,
            "description": (f"spider2-lite {engine} database {db_name}: "
                            f"{len(tables)} tables across "
                            f"{len(cat.namespaces)} dataset(s). Schema and column "
                            f"descriptions come from the catalog shipped with "
                            f"Spider2; no warehouse query was run."),
            # one catalog, one schema, every table: SearchContext reads
            # catalogs[0].schemas[0].tables, and a BigQuery database spans several
            # datasets, so splitting by dataset would hide all but the first.
            "schemas": [{"name": "all",
                         "description": "every dataset in this database, flattened; "
                                        "table names are fully qualified",
                         "tables": tables}],
        }]},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{db_name}.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    chunks = chunk_texts(tables)
    n_fk = sum(len(t["foreign_keys"]) for t in tables)
    info = {"db": db_name, "tables_raw": raw, "tables": len(tables),
            "families": len(families), "chunks": len(chunks), "fks": n_fk}
    if not embed:
        return info

    import numpy as np
    from sentence_transformers import SentenceTransformer

    enc = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    vecs = enc.encode([DOC_PREFIX + c for c in chunks],
                      batch_size=64, normalize_embeddings=True,
                      show_progress_bar=False)
    np.savez_compressed(
        out_dir / f"{db_name}.npz",
        chunks=np.array(chunks, dtype=object).astype("U") if False
        else np.array(chunks),
        vecs=np.asarray(vecs, dtype="float32"),
        model_id=np.array([EMBED_MODEL]),
        query_prefix=np.array([QUERY_PREFIX]),
        doc_prefix=np.array([DOC_PREFIX]))
    info["dim"] = int(np.asarray(vecs).shape[1])
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="spider2_lite_bq",
                    help="DATA_SOURCES key; its dialect picks the catalog engine")
    ap.add_argument("--db", action="append",
                    help="one database (repeatable); default every database in the "
                         "source")
    ap.add_argument("--all", action="store_true", help="explicit form of the default")
    ap.add_argument("--out", default=None,
                    help="default: spider2-dce/output/<engine>/")
    ap.add_argument("--no-embed", action="store_true",
                    help="write the YAML only; skip the embedding model")
    ap.add_argument("--force", action="store_true",
                    help="rebuild databases that already have an index")
    args = ap.parse_args()

    src = DATA_SOURCES.get(args.source)
    if src is None:
        raise SystemExit(f"unknown --source {args.source!r}; "
                         f"choose from {sorted(DATA_SOURCES)}")
    engine = {"bigquery": "bigquery", "snowflake": "snowflake"}.get(src.dialect)
    if engine is None:
        raise SystemExit(f"--source {args.source} is {src.dialect}; this builds "
                         f"indexes for the warehouse lanes only")

    out_dir = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "spider2-dce" / "output" / engine)

    if args.db:
        dbs = args.db
    else:
        from run_benchmark import load_questions
        dbs = sorted({q["db"] for q in load_questions([src])})
    print(f"{len(dbs)} database(s) from {args.source} ({engine}) -> {out_dir}")

    rows, t0 = [], time.time()
    for i, db in enumerate(dbs, 1):
        if not args.force and (out_dir / f"{db}.yaml").exists() and (
                args.no_embed or (out_dir / f"{db}.npz").exists()):
            print(f"[{i}/{len(dbs)}] {db}: already built, skipping")
            continue
        print(f"[{i}/{len(dbs)}] {db} ... ", end="", flush=True)
        try:
            info = build_db(db, engine, out_dir, embed=not args.no_embed)
        except Exception as e:
            info = {"db": db, "error": f"{type(e).__name__}: {e}"}
        rows.append(info)
        if info.get("error"):
            print(f"FAILED: {info['error']}")
        else:
            print(f"{info['tables_raw']} -> {info['tables']} tables "
                  f"({info['families']} sharded families), "
                  f"{info['chunks']} chunks, {info['fks']} prose FKs")

    ok = [r for r in rows if not r.get("error")]
    bad = [r for r in rows if r.get("error")]
    print(f"\nbuilt {len(ok)} database(s) in {(time.time() - t0) / 60:.1f} min")
    if ok:
        print(f"  tables   : {sum(r['tables_raw'] for r in ok)} in the catalog -> "
              f"{sum(r['tables'] for r in ok)} after collapsing "
              f"{sum(r['families'] for r in ok)} sharded families")
        print(f"  chunks   : {sum(r['chunks'] for r in ok)}")
        print(f"  prose FKs: {sum(r['fks'] for r in ok)} recovered from descriptions")
    for r in bad:
        print(f"  FAILED {r['db']}: {r['error']}")
    (out_dir / "build_report.json").write_text(json.dumps(rows, indent=1),
                                               encoding="utf-8")
    print(f"  report   : {out_dir / 'build_report.json'}")
    print("\nNo warehouse query was issued and no LLM was called: every field above "
          "comes from the catalog spider2-lite ships.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
