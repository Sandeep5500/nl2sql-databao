#!/usr/bin/env python3
"""Bring search_context in line with describe_table: rewrite the context
engine's table/column descriptions from the column profile and the explored
notes, then re-embed.

Each description becomes: the computed profile of the column (facts), followed
by its explored note when one survived the checking pass. The old descriptions
(written from five sample rows) are dropped. The originals are copied to
spider2-dce/output/databases_pre_explore/ first.

Usage (from repo root; no benchmark run may be reading dce.duckdb):
    uv run --project nl2sql-v2 python scripts/apply_notes_to_dce.py --write
    DCE_OLLAMA_HOST=<node> uv run --project nl2sql-v2 python scripts/apply_notes_to_dce.py --index
"""

import argparse
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nl2sql-v2/src"))
from nl2sql.config import DCE_PROJECT_DIR  # noqa: E402
from nl2sql.context import TableContext  # noqa: E402

OUT = DCE_PROJECT_DIR / "output" / "databases"
BACKUP = DCE_PROJECT_DIR / "output" / "databases_pre_explore"


def rewrite(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    src_dir = BACKUP if BACKUP.exists() else OUT
    n_tables = n_cols = n_notes = 0
    for src in sorted(src_dir.glob("*.yaml")):
        doc = yaml.safe_load(src.read_text())
        tc = TableContext(DCE_PROJECT_DIR, f"databases/{src.name}", explored=True)
        explored = {k.lower(): v for k, v in (tc.explored.get("tables") or {}).items()}
        for cat in doc["context"]["catalogs"]:
            for schema in cat["schemas"]:
                for t in schema["tables"]:
                    n_tables += 1
                    rec = explored.get(t["name"].lower()) or {}
                    def text(x):  # the fact left by the checking and rewriting passes
                        if x.get("verdict") == "no":
                            return ""
                        return " ".join(str(x.get("fact", x.get("note", ""))).split())
                    parts = [" ".join(str(rec.get("table_fact",
                                                  rec.get("table_note", ""))).split())]
                    parts += tc.key_lines(t["name"])
                    parts += [text(p) for p in rec.get("pitfalls") or [] if text(p)]
                    desc = " ".join(p for p in parts if p)
                    if desc:
                        t["description"] = desc
                    notes = {str(c.get("column", "")).lower(): text(c)
                             for c in rec.get("column_notes") or [] if text(c)}
                    for c in t.get("columns") or []:
                        n_cols += 1
                        prof = tc.profile(t["name"], c["name"])
                        note = notes.get(c["name"].lower(), "")
                        n_notes += bool(note)
                        c["description"] = " ".join(x for x in (
                            f"Values: {prof}." if prof else "", note) if x) or None
        (dest / src.name).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    print(f"wrote {n_tables} tables, {n_cols} columns ({n_notes} with an explored note) "
          f"to {dest}")


def index() -> None:
    from databao_context_engine.build_sources.build_wiring import index_built_contexts
    from databao_context_engine.datasources.datasource_context import (
        get_all_contexts,  # noqa: F401  (import check: fails early if the API moved)
    )
    from databao_context_engine.plugins.plugin_loader import DatabaoContextPluginLoader
    from databao_context_engine.project.layout import ensure_project_dir

    layout = ensure_project_dir(project_dir=DCE_PROJECT_DIR)
    contexts = get_all_contexts(layout)
    results = index_built_contexts(layout, DatabaoContextPluginLoader(), contexts)
    print([(str(r.datasource_id), str(r.status)) for r in results])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="back up the current records and write the new descriptions")
    ap.add_argument("--preview-dir", help="write the new records here instead (no backup, "
                                          "nothing the engine reads is touched)")
    ap.add_argument("--index", action="store_true", help="re-embed from the records")
    args = ap.parse_args()
    if args.preview_dir:
        rewrite(Path(args.preview_dir))
    if args.write:
        if not BACKUP.exists():
            shutil.copytree(OUT, BACKUP)
        rewrite(OUT)
    if args.index:
        index()


if __name__ == "__main__":
    main()
