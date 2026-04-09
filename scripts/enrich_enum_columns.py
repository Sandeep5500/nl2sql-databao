#!/usr/bin/env python3
"""Enum enrichment pass for DCE YAML files.

Scans every table's sample rows in each enriched YAML, identifies
low-cardinality TEXT columns (likely categorical/coded), and appends
the observed distinct values to the column description so the agent
can filter correctly without guessing.

This addresses the B5 failure class: agent writes correct SQL structure
but uses wrong literal in WHERE clause (e.g. 'helmet used' instead of 'E'),
producing an empty result.

Limitations
-----------
- Only uses sample rows already stored in the YAML (typically 5 per table).
  May not capture all enum values for large domains; re-running `dce build`
  with --sample-rows 30 first gives better coverage.
- Does NOT re-run dce build. After running this script, run:
    cd spider2-dce && dce build
  to re-embed the enriched descriptions into dce.duckdb.

Usage
-----
    # Dry run — print proposed changes, modify nothing:
    python scripts/enrich_enum_columns.py --dry-run

    # Apply to all YAMLs:
    python scripts/enrich_enum_columns.py

    # Apply to specific databases only:
    python scripts/enrich_enum_columns.py --db california_traffic_collision school_scheduling

    # Tune thresholds:
    python scripts/enrich_enum_columns.py --max-distinct 20 --min-samples 2
"""

from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_DIR = REPO_ROOT / "spider2-dce" / "output" / "databases"

# Columns whose names strongly suggest they are free-text (high-cardinality)
# even if the 5-row sample happens to look categorical. Skip these.
FREE_TEXT_PATTERNS = re.compile(
    r"(name|description|address|road|street|city|county|comment|note|text|"
    r"reason|detail|remarks|url|email|phone|title|label|path|filename|"
    r"primary_road|secondary_road|officer_id|beat_number|reporting_district)",
    re.IGNORECASE,
)

# Columns where adding sample values is actively harmful (e.g. IDs, hashes)
ID_PATTERNS = re.compile(
    r"(_id|_key|_hash|_uuid|_token|_code$|rowguid|guid|uuid|"
    r"case_id|order_id|customer_id|product_id|invoice_id|track_id|"
    r"album_id|artist_id|genre_id|tracking)",
    re.IGNORECASE,
)

# If description already mentions sample values / distinct values, skip
ALREADY_ENRICHED_RE = re.compile(
    r"(sample value|distinct value|possible value|valid value|one of:|e\.g\.,?\s*['\"])",
    re.IGNORECASE,
)


def is_skippable_column(col: dict) -> bool:
    name = col.get("name", "")
    col_type = col.get("type", "").upper()
    # Only enrich TEXT/VARCHAR columns
    if col_type not in ("TEXT", "VARCHAR", "STRING", "CHAR"):
        return True
    if ID_PATTERNS.search(name):
        return True
    if FREE_TEXT_PATTERNS.search(name):
        return True
    desc = col.get("description") or ""
    if ALREADY_ENRICHED_RE.search(desc):
        return True
    return False


def collect_distinct_values(table: dict, col_name: str) -> list[str]:
    """Collect distinct non-null values for col_name from table sample rows."""
    samples = table.get("samples") or []
    seen: list[str] = []
    seen_set: set[str] = set()
    for row in samples:
        val = row.get(col_name)
        if val is None or val == "":
            continue
        s = str(val).strip()
        if s and s not in seen_set:
            seen_set.add(s)
            seen.append(s)
    return seen


def format_enum_note(values: list[str]) -> str:
    """Format the distinct values as a short appended note."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"Known sample values: {quoted}."


def enrich_yaml(yaml_path: Path, max_distinct: int, min_samples: int, dry_run: bool) -> int:
    """Enrich one YAML file. Returns count of columns updated."""
    with yaml_path.open() as f:
        doc = yaml.safe_load(f)

    updated = 0
    changes: list[str] = []

    for catalog in doc.get("context", {}).get("catalogs", []):
        for schema in catalog.get("schemas", []):
            for table in schema.get("tables", []):
                table_name = table.get("name", "?")
                samples = table.get("samples") or []
                if len(samples) < min_samples:
                    continue

                for col in table.get("columns", []):
                    if is_skippable_column(col):
                        continue

                    values = collect_distinct_values(table, col["name"])
                    if not values:
                        continue
                    # Only enrich if values look like a small finite domain
                    if len(values) > max_distinct:
                        continue
                    # Skip if the only "value" is the column name itself (header leak)
                    if len(values) == 1 and values[0].upper() == col["name"].upper():
                        continue
                    # Skip if all values look like UUIDs or long free text
                    if all(len(v) > 30 for v in values):
                        continue
                    # Skip if any value looks like a UUID
                    uuid_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
                    if any(uuid_re.match(v) for v in values):
                        continue

                    note = format_enum_note(values)
                    current_desc = (col.get("description") or "").strip()

                    # Don't duplicate if already added
                    if note in current_desc:
                        continue

                    new_desc = f"{current_desc} {note}".strip()
                    col["description"] = new_desc
                    updated += 1
                    changes.append(
                        f"  {table_name}.{col['name']}: +{len(values)} values → {values}"
                    )

    if changes:
        db_name = yaml_path.stem
        print(f"\n{'[DRY RUN] ' if dry_run else ''}{'=' * 60}")
        print(f"  {db_name} — {len(changes)} column(s) enriched:")
        for c in changes:
            print(c)

    if updated > 0 and not dry_run:
        # Backup original before writing
        backup = yaml_path.with_suffix(".yaml.pre_enum_bak")
        if not backup.exists():
            shutil.copy2(yaml_path, backup)
        with yaml_path.open("w") as f:
            yaml.dump(doc, f, allow_unicode=True, sort_keys=False, width=120)

    return updated


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich DCE YAML files with enum/categorical column values.")
    ap.add_argument("--yaml-dir", type=Path, default=YAML_DIR,
                    help="Directory containing enriched DCE YAML files.")
    ap.add_argument("--db", nargs="+", default=None,
                    help="Limit to specific DB names (e.g. california_traffic_collision school_scheduling).")
    ap.add_argument("--max-distinct", type=int, default=15,
                    help="Max distinct values to be considered categorical (default: 15).")
    ap.add_argument("--min-samples", type=int, default=2,
                    help="Skip tables with fewer than this many sample rows (default: 2).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print proposed changes without modifying any files.")
    args = ap.parse_args()

    yaml_files = sorted(args.yaml_dir.glob("*.yaml"))
    if not yaml_files:
        print(f"No YAML files found in {args.yaml_dir}")
        return

    if args.db:
        requested = {d.lower().replace("-", "_") for d in args.db}
        yaml_files = [f for f in yaml_files if f.stem.lower().replace("-", "_") in requested]
        if not yaml_files:
            print(f"No matching YAML files for: {args.db}")
            return

    total_cols = 0
    total_dbs = 0
    for yf in yaml_files:
        n = enrich_yaml(yf, args.max_distinct, args.min_samples, args.dry_run)
        if n > 0:
            total_cols += n
            total_dbs += 1

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Done — {total_cols} column(s) enriched across {total_dbs} database(s).")
    if not args.dry_run and total_cols > 0:
        print("\nNext step: re-run dce build to re-embed the enriched descriptions:")
        print("  cd spider2-dce && dce build")
    elif args.dry_run and total_cols > 0:
        print("\nRe-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
