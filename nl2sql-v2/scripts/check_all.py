#!/usr/bin/env python3
"""Run every offline check. No GPU, no credentials, no Spider2 checkout required.

This is the gate: it is what should pass before any GPU time or Snowflake credit is
spent, and what Modal's smoke function runs first.

    uv run --extra dbt python scripts/check_all.py

The dbt checks are skipped (not failed) when dbt is not installed, so the suite is
still useful in an environment without the dbt extra.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "src"))

# (script, args, needs_dbt)
CHECKS = [
    # --ref, not --check: the frozen baseline_prompts.json predates the team's
    # checklist change, so the live comparison against origin/main is the real
    # guarantee that the SQLite lane still matches theirs.
    ("check_prompt_parity.py", ["--ref", "origin/main"], False),
    ("check_schema_dump.py", [], False),
    ("check_retrieval_wiring.py", [], False),
    ("check_sources.py", [], False),
    ("check_sqlite_episode.py", [], False),
    ("check_snowflake_db.py", [], False),
    ("check_bigquery_db.py", [], False),
    ("check_dbt_lane.py", [], True),
    ("check_dbt_episode.py", [], True),
]


def main() -> int:
    try:
        from nl2sql.dbt_tools import dbt_executable
        have_dbt = dbt_executable() is not None
    except Exception:
        have_dbt = False

    results = []
    for script, args, needs_dbt in CHECKS:
        if needs_dbt and not have_dbt:
            print(f"-- {script}: SKIPPED (dbt not installed)")
            results.append((script, "skip"))
            continue
        print(f"\n{'=' * 70}\n== {script}\n{'=' * 70}")
        proc = subprocess.run([sys.executable, str(HERE / script), *args])
        results.append((script, "pass" if proc.returncode == 0 else "FAIL"))

    print(f"\n{'=' * 70}\nsummary\n{'=' * 70}")
    for script, status in results:
        print(f"  {status:5s} {script}")
    failed = [s for s, st in results if st == "FAIL"]
    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    skipped = [s for s, st in results if st == "skip"]
    if skipped:
        print(f"\nall run checks passed ({len(skipped)} skipped: install the dbt "
              f"extra to cover the dbt lane)")
    else:
        print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
