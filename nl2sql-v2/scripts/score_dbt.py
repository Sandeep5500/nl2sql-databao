#!/usr/bin/env python3
"""Score a Spider 2.0-DBT submission with Spider2's own match functions.

Drives their eval_utils directly rather than shelling out to their evaluate.py, for
two reasons: we want a per-instance row (theirs prints an aggregate), and theirs has
an `import pdb; pdb.set_trace()` in an exception path, which would hang a detached
run. `--their-evaluate` is still available as a cross-check.

Contract (verified against their evaluate.py):
    gold entry   : gold/spider2_eval.jsonl -> {instance_id, evaluation:{func,parameters}}
    our metadata : results_metadata.jsonl  -> {instance_id, answer_type, answer_or_path}
    gold file    : <gold_dir>/<instance_id>/<parameters.gold>
    our file     : <result_dir>/<instance_id>/<answer_or_path>

    uv run python scripts/score_dbt.py ../results/dbt_run
    uv run python scripts/score_dbt.py --self-test        # gold against itself
"""

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl2sql.config import DBT_EVAL_SUITE
from nl2sql.dbt_submission import (GOLD_JSONL, gold_db_name,
                                   load_gold_config, resolve_gold_db)

FIELDNAMES = ["instance_id", "db", "score", "score_detail", "status", "steps",
              "critic_rounds", "search_calls", "draft_calls", "wall_seconds", "sql"]


def load_eval_utils(suite: Path):
    """Import their eval_utils by path (the suite is not an installed package)."""
    p = suite / "eval_utils.py"
    if not p.exists():
        return None, f"no eval_utils.py in {suite}"
    # their module imports bigquery/snowflake helpers at module scope in some
    # releases; report that rather than crashing with a bare ImportError
    spec = importlib.util.spec_from_file_location("spider2_dbt_eval_utils", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    sys.path.insert(0, str(suite))
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        return None, f"could not import their eval_utils: {type(e).__name__}: {e}"
    return mod, ""


def evaluations(gold_entry: dict) -> list[dict]:
    ev = gold_entry.get("evaluation")
    if ev is None:
        return []
    return ev if isinstance(ev, list) else [ev]


def score_one(iid, mine, gold_entry, result_dir: Path, gold_dir: Path, utils):
    """One instance, through whichever matcher its gold entry declares."""
    answer_type = mine.get("answer_type")
    answer = str(mine.get("answer_or_path", ""))
    best, detail = 0, "no_matcher_ran"

    for ev in evaluations(gold_entry):
        func = ev.get("func")
        params = dict(ev.get("parameters") or {})
        fn = getattr(utils, str(func), None)
        if fn is None:
            detail = f"matcher_missing:{func}"
            continue
        try:
            if func in ("string_match", "number_match"):
                score = fn(answer, **params)
            elif func == "duckdb_match":
                gold_name = params.pop("gold", None)
                gold_path, repaired = resolve_gold_db(gold_dir, iid, gold_name)
                if gold_path is None:
                    return 0, (f"gold_db_missing:{gold_name} "
                               f"(not in their archive; exclude from the "
                               f"denominator)")
                if repaired:
                    func = func + "(gold filename repaired)"
                pred_path = result_dir / iid / answer
                if not pred_path.exists():
                    return 0, f"our_db_missing:{answer}"
                score = fn(str(pred_path), gold=str(gold_path), **params)
            elif func in ("table_match", "tables_match"):
                gold_name = params.pop("gold", None)
                if isinstance(gold_name, list):
                    gold_arg = [str(gold_dir / iid / g) for g in gold_name]
                else:
                    gold_arg = str(gold_dir / iid / str(gold_name))
                score = fn(str(result_dir / iid / answer), gold=gold_arg, **params)
            else:
                detail = f"unsupported_func:{func}"
                continue
        except TypeError as e:
            # their signatures have moved between releases: say so loudly instead of
            # scoring everything 0 and calling it a result
            return 0, f"matcher_signature_mismatch:{func}: {e}"
        except Exception as e:
            detail = f"match_error:{func}: {type(e).__name__}: {e}"
            continue
        score = int(bool(score))
        if score > best:
            best, detail = score, func
        elif best == 0:
            detail = func
    return best, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submission", nargs="?", default="")
    ap.add_argument("--suite", default=str(DBT_EVAL_SUITE))
    ap.add_argument("--output", help="per-instance CSV (default <submission>/scored.csv)")
    ap.add_argument("--their-evaluate", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="score the gold databases against themselves; anything "
                         "below 68/68 means the track is blocked on their tooling")
    args = ap.parse_args()

    suite = Path(args.suite)
    gold_dir = suite / "gold"
    if not suite.exists():
        raise SystemExit(f"evaluation suite not found at {suite} "
                         f"(run: git submodule update --init Spider2)")

    gold = load_gold_config(gold_dir)
    if not gold:
        raise SystemExit(f"no {GOLD_JSONL} in {gold_dir}")
    print(f"gold entries: {len(gold)}")

    utils, err = load_eval_utils(suite)
    if utils is None:
        raise SystemExit(err)

    if args.self_test:
        # Score each gold database against ITSELF, in place. The earlier version
        # built a real submission folder first, which meant copying gigabytes of
        # DuckDB files between volumes to learn something that needs no copy at all.
        # What this verifies: their matcher imports and runs, and every gold database
        # actually contains the condition_tabs its own entry checks.
        absent, ok, bad = [], 0, []
        for iid, entry in sorted(gold.items()):
            name = gold_db_name(entry)
            src, _ = resolve_gold_db(gold_dir, iid, name)
            if src is None:
                d = gold_dir / iid
                present = ([q.name for q in sorted(d.iterdir())]
                           if d.is_dir() else ["<no directory>"])
                absent.append((f"{iid}/{name}", present))
                continue
            mine = {"answer_type": "file", "answer_or_path": src.name}
            score, detail = score_one(iid, mine, entry, gold_dir, gold_dir, utils)
            if score:
                ok += 1
            else:
                bad.append((iid, detail))

        print(f"\ngold scored against itself: {ok}/{len(gold)}")
        if absent:
            print(f"\nBLOCKER: {len(absent)} gold databases the config names are "
                  f"not present:")
            for item, present in absent:
                print(f"  {item:44s} dir contains: {present}")
            print("  -> re-run spider2-dbt/setup.py, or these instances cannot be "
                  "scored and must come out of the denominator")
        if bad:
            print(f"\nBLOCKER: {len(bad)} gold databases do not satisfy their own "
                  f"gold condition:")
            for iid, detail in bad:
                print(f"  {iid:24s} {detail}")
            print("  -> a defect in their suite, not in our output")
        print(f"\nscoreable dbt denominator: {ok}/{len(gold)}")
        if ok != len(gold):
            print("Report any dbt accuracy against that denominator, not "
                  f"{len(gold)}.")
            return 1
        return 0

    if not args.submission:
        raise SystemExit("pass a submission folder (or use --self-test)")
    result_dir = Path(args.submission)
    meta_path = result_dir / "results_metadata.jsonl"
    if not meta_path.exists():
        raise SystemExit(f"no results_metadata.jsonl in {result_dir}")
    submitted = {}
    with open(meta_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                submitted[row["instance_id"]] = row

    if args.their_evaluate:
        argv = [sys.executable, str(suite / "evaluate.py"),
                "--result_dir", str(result_dir), "--gold_dir", str(gold_dir)]
        print("running: " + " ".join(argv))
        return subprocess.run(argv, cwd=str(suite)).returncode

    out_path = Path(args.output) if args.output else result_dir / "scored.csv"
    correct, details = 0, {}
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for iid in sorted(gold):
            mine = submitted.get(iid)
            if mine is None:
                writer.writerow({"instance_id": iid, "db": iid, "score": 0,
                                 "score_detail": "not_submitted", "status": "missing"})
                details["not_submitted"] = details.get("not_submitted", 0) + 1
                continue
            score, detail = score_one(iid, mine, gold[iid], result_dir, gold_dir, utils)
            correct += score
            details[detail] = details.get(detail, 0) + 1
            writer.writerow({"instance_id": iid, "db": iid, "score": score,
                             "score_detail": detail, "status": "scored",
                             "sql": (mine.get("description") or "").replace("\n", "\\n")})

    # Report both denominators. A partial run otherwise looks catastrophic:
    # the scorer walks the whole gold set, so every instance that was never
    # attempted counts as not_submitted.
    attempted = len([i for i in gold if i in submitted])
    print(f"\n{correct}/{attempted} correct of those submitted "
          f"({100.0 * correct / max(attempted, 1):.1f}%)")
    if attempted != len(gold):
        print(f"{correct}/{len(gold)} against the full gold set "
              f"({len(gold) - attempted} instances were not run)")
    for k, n in sorted(details.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {k}")
    print(f"per-instance rows: {out_path}")
    if args.self_test and correct != len(gold):
        print("\nBLOCKER: the gold does not score against itself. Fix the suite or "
              "the unpacked databases before trusting any dbt number.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
