#!/usr/bin/env python3
"""Size the snow/dbt target sets and verify they are actually scoreable.

Step 0 of the platform work. Answers, before any compute is spent:
  * how many snow instances there are per origin prefix (sf_local / sf_bq / sf_ga / sf)
  * which target instances have NO gold exec CSV -- those are unscoreable and must come
    out of the denominator up front, not be discovered mid-run
  * which have no eval-jsonl entry (they still score, but on default
    condition_cols/ignore_order, which is worth knowing)
  * whether the sf_local ids map 1:1 onto our local### ids (the control arm's premise)
  * how many dbt example projects exist and which look structurally complete

    uv run python scripts/census_targets.py
    uv run python scripts/census_targets.py --write-unscoreable ../results/unscoreable.txt
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import (DBT_EXAMPLES_DIR, DBT_QUESTIONS_FILE, QUESTIONS_FILE,
                           SNOW_EVAL_JSONL, SNOW_GOLD_EXEC_DIR, SNOW_GOLD_SQL_DIR,
                           SNOW_QUESTIONS_FILE)

# longest first: "sf_local003" must not be counted into the bare "sf" family
PREFIXES = ("sf_local", "sf_bq", "sf_ga", "sf")


def origin(instance_id):
    for p in PREFIXES:
        if instance_id.startswith(p):
            return p
    return "other"


def read_jsonl(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def gold_ids(gold_dir):
    """Instance ids with at least one gold CSV. Spider2 allows per-instance
    alternates (foo_a.csv / foo_b.csv), which eval.py already globs for."""
    if not gold_dir.exists():
        return set()
    out = set()
    for entry in gold_dir.iterdir():
        m = re.match(r"^(.*?)(_[a-z])?\.csv$", entry.name)
        if m:
            out.add(m.group(1))
    return out


def section(title):
    print("\n" + title)
    print("-" * len(title))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-unscoreable", metavar="PATH",
                    help="write the unscoreable target instance_ids, one per line")
    args = ap.parse_args()

    problems = []

    section("spider2-snow")
    snow = []
    if not SNOW_QUESTIONS_FILE.exists():
        print("MISSING " + str(SNOW_QUESTIONS_FILE))
        print("  -> run: git submodule update --init Spider2")
        problems.append("snow questions file missing")
    else:
        snow = read_jsonl(SNOW_QUESTIONS_FILE)
        print(SNOW_QUESTIONS_FILE.name + ": " + str(len(snow)) + " instances")
        counts = Counter(origin(r["instance_id"]) for r in snow)
        for p in PREFIXES + ("other",):
            if counts.get(p):
                print("  {:14s} {:4d}".format(p + "###", counts[p]))
        print("  fields: " + str(sorted({k for r in snow for k in r})))

    if snow:
        target = [r for r in snow if origin(r["instance_id"]) != "sf_local"]
        control = [r for r in snow if origin(r["instance_id"]) == "sf_local"]
        print("\ntarget set (non-sf_local): " + str(len(target))
              + "   control (sf_local): " + str(len(control)))

        have_gold = gold_ids(SNOW_GOLD_EXEC_DIR)
        if not have_gold:
            print("MISSING gold exec dir " + str(SNOW_GOLD_EXEC_DIR))
            problems.append("snow gold exec_result missing")
        else:
            print("gold exec CSVs cover " + str(len(have_gold)) + " instance ids")
            missing = sorted(r["instance_id"] for r in target
                             if r["instance_id"] not in have_gold)
            print("  scoreable target instances: "
                  + str(len(target) - len(missing)) + "/" + str(len(target)))
            if missing:
                shown = ", ".join(missing[:12]) + (" ..." if len(missing) > 12 else "")
                print("  UNSCOREABLE (" + str(len(missing)) + "): " + shown)
                print("  -> exclude these from the denominator when reporting")
                if args.write_unscoreable:
                    Path(args.write_unscoreable).write_text(
                        "\n".join(missing) + "\n", encoding="utf-8")
                    print("  -> written to " + args.write_unscoreable)

        standards = {r["instance_id"] for r in read_jsonl(SNOW_EVAL_JSONL)}
        if not standards:
            print("MISSING eval jsonl " + str(SNOW_EVAL_JSONL))
            problems.append("snow eval jsonl missing")
        else:
            no_std = [r["instance_id"] for r in target
                      if r["instance_id"] not in standards]
            print("eval-jsonl standards: " + str(len(standards)) + " entries; "
                  + str(len(no_std)) + " target instances fall back to defaults")

        n_gold_sql = (len(list(SNOW_GOLD_SQL_DIR.iterdir()))
                      if SNOW_GOLD_SQL_DIR.exists() else 0)
        print("gold SQL files: " + str(n_gold_sql)
              + " (only needed for oracle-style arms)")

        section("sf_local <-> local 1:1 mapping (control arm premise)")
        lite = read_jsonl(QUESTIONS_FILE)
        if not lite:
            print("MISSING " + str(QUESTIONS_FILE) + " - cannot verify the mapping")
        else:
            local_ids = {r["instance_id"] for r in lite
                         if r["instance_id"].startswith("local")}
            twin_ids = {r["instance_id"][len("sf_"):] for r in control}
            print("lite local###: " + str(len(local_ids))
                  + "   snow sf_local###: " + str(len(twin_ids)))
            only_lite = sorted(local_ids - twin_ids)
            only_snow = sorted(twin_ids - local_ids)
            if not only_lite and not only_snow:
                print("  1:1 - the control arm is valid")
            else:
                print("  NOT 1:1 - only in lite: " + str(only_lite[:10]))
                print("            only in snow: " + str(only_snow[:10]))
                problems.append("sf_local/local mapping is not 1:1")

    section("spider2-dbt")
    if not DBT_QUESTIONS_FILE.exists():
        print("MISSING " + str(DBT_QUESTIONS_FILE))
        problems.append("dbt questions file missing")
    else:
        dbt = read_jsonl(DBT_QUESTIONS_FILE)
        print(DBT_QUESTIONS_FILE.name + ": " + str(len(dbt)) + " instances")
        print("  fields: " + str(sorted({k for r in dbt for k in r})))
        dirs = (sorted(p for p in DBT_EXAMPLES_DIR.iterdir() if p.is_dir())
                if DBT_EXAMPLES_DIR.exists() else [])
        print("  project dirs: " + str(len(dirs)))
        no_dir = [r["instance_id"] for r in dbt
                  if not (DBT_EXAMPLES_DIR / r["instance_id"]).is_dir()]
        if no_dir:
            print("  instances with NO project dir (" + str(len(no_dir)) + "): "
                  + str(no_dir[:10]))
            problems.append("dbt instances missing project dirs")
        incomplete = [d.name for d in dirs
                      if not (d / "dbt_project.yml").exists()
                      or not (d / "profiles.yml").exists()]
        if incomplete:
            print("  dirs missing dbt_project.yml/profiles.yml ("
                  + str(len(incomplete)) + "): " + str(incomplete[:10]))

        # The gold DuckDB databases decide the scoreable denominator, and they
        # are a separate download (spider2-dbt/README.md -> setup.py). Scoring
        # is impossible without them, so this is a blocker, not a note.
        from nl2sql.config import DBT_EVAL_SUITE
        from nl2sql.dbt_submission import gold_db_name, load_gold_config
        gold_dir = DBT_EVAL_SUITE / "gold"
        gold = load_gold_config(gold_dir)
        print("  gold entries: " + str(len(gold)))
        if not gold:
            problems.append("dbt gold config missing "
                            "(evaluation_suite/gold/spider2_eval.jsonl)")
        else:
            absent = []
            for iid, entry in sorted(gold.items()):
                name = gold_db_name(entry)
                if name and not (gold_dir / iid / name).exists():
                    absent.append(iid + "/" + name)
            print("  scoreable dbt instances: "
                  + str(len(gold) - len(absent)) + "/" + str(len(gold)))
            if absent:
                print("  gold databases ABSENT (" + str(len(absent)) + "): "
                      + str(absent[:8]))
                problems.append(str(len(absent)) + " dbt gold databases are "
                                "absent; those instances cannot be scored")

    section("verdict")
    if problems:
        for p in problems:
            print("BLOCKER: " + p)
        return 1
    print("census clean - target sets sized and scoreable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
