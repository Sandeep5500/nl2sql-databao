#!/usr/bin/env python3
"""
Generate DCE datasource YAML configs for all Spider 2.0 SQLite databases
and verify connections.

Run after downloading SQLite files to spider2-localdb/:
  python setup_dce_spider2.py

Expects sqlite files at:
  <repo>/Spider2/spider2-lite/resource/databases/sqlite/
"""

import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
SQLITE_DIR = str(_REPO_ROOT / "Spider2" / "spider2-lite" / "resource" / "databases" / "sqlite")
DCE_OUTPUT_DIR = str(_REPO_ROOT / "spider2-dce" / "src" / "databases")

# Exclude oracle_sql — broken view (emp_hire_periods_with_name) that crashes DuckDB schema inspection
EXCLUDE_DBS = {"oracle_sql"}

def main():
    if not os.path.isdir(SQLITE_DIR):
        print(f"ERROR: SQLite directory not found: {SQLITE_DIR}")
        print("Please download SQLite files from Google Drive first (see progress/setup_status.txt)")
        sys.exit(1)

    sqlite_files = sorted(f for f in os.listdir(SQLITE_DIR) if f.endswith(".sqlite"))
    if not sqlite_files:
        print(f"ERROR: No .sqlite files found in {SQLITE_DIR}")
        print("Please download and unzip the SQLite files from Google Drive.")
        sys.exit(1)

    os.makedirs(DCE_OUTPUT_DIR, exist_ok=True)

    generated = []
    skipped = []

    for fname in sqlite_files:
        db_name = fname.replace(".sqlite", "")
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", db_name).lower()

        if safe_name in EXCLUDE_DBS or db_name.lower() in EXCLUDE_DBS:
            skipped.append(db_name)
            print(f"  SKIP  {db_name} (broken views, excluded)")
            continue

        db_path = os.path.join(SQLITE_DIR, fname)
        yaml_content = f"""type: sqlite
name: {safe_name}
connection:
  database_path: {db_path}
"""
        out_path = os.path.join(DCE_OUTPUT_DIR, f"{safe_name}.yaml")
        with open(out_path, "w") as f:
            f.write(yaml_content)

        generated.append(safe_name)
        print(f"  OK    {safe_name}.yaml → {db_path}")

    print(f"\nGenerated {len(generated)} configs, skipped {len(skipped)}")
    print(f"Output: {DCE_OUTPUT_DIR}")
    print("\nNext steps:")
    print(f"  cd {_REPO_ROOT / 'spider2-dce'}")
    print(f"  alias dce='uv --project {_REPO_ROOT / 'databao-context-engine'} run dce'")
    print("  dce datasource check")
    print("  dce build")
    print("  dce index")

if __name__ == "__main__":
    main()