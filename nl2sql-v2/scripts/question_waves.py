#!/usr/bin/env python3
"""Claude-written question waves for the judge data (BIRD-Platinum databases): writer folders and
assignment messages, blind-solve files, the checks, admission into the question set, and the
sync to Babel. Recovered from the Oct 31 - Nov 1 run (make_wave.py, validate_writer.sh,
admit.py, whose scratchpad copies were lost) and moved to a durable root.

Root (QW_ROOT, default ~/judge-work): bird_plat/ (the question set, pulled from Babel; databases/
links into docs/), docs/<db>/ (BIRD database folders: the .sqlite file and database_description/),
venv/ (duckdb 1.5.5, pandas, sqlglot, openai), full_run/ (writer and solver folders, reviews).

    python scripts/question_waves.py plan                 # full_run/plan.json: writer -> databases
    python scripts/question_waves.py plan --copy fw:hw    # a new wave (hw01..) on fw01..'s databases
    python scripts/question_waves.py setup fw07,fw08      # folders + existing_<db>.txt, prints assignments
    python scripts/question_waves.py solve fw07,fw08      # blind questions file, prints solver assignments
    python scripts/question_waves.py validate fw07        # solve check, stress test, review packets
    python scripts/question_waves.py admit fw07 fw08 [--reviews a.jsonl,b.jsonl]
    python scripts/question_waves.py sync --job <babel session job id>

Writers are Sonnet subagents, solvers and reviewers Opus (briefs in scripts/question_briefs/).
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("QW_ROOT", Path.home() / "judge-work"))
DS, RUN, DOCS, PY = ROOT / "bird_plat", ROOT / "full_run", ROOT / "docs", ROOT / "venv/bin/python"
REPO = Path(__file__).resolve().parents[2]
DONE = {"car_retails", "hockey", "beer_factory", "movies_4"}  # 10+ written in the smoke test
# "focus" (Nov 7): weighted to the agent's Spider2 failure types (look-alike columns, grain);
# "original" is the Oct 31 mix; "hard" (Nov 9) follows the brief's Difficulty section, with more
# fanout, the kind the agent split on most often in the Nov 7 batch (35% vs 21-28%).
MIX = {"hard": {"train": "2 plain, 3 lookalike_columns, 2 grain, 3 fanout",
                "heldout": "1 plain, 1 lookalike_columns, 1 grain, 2 fanout"},
       "focus": {"train": "2 plain, 3 lookalike_columns, 3 grain, 2 fanout",
                 "heldout": "1 plain, 2 lookalike_columns, 1 grain, 1 fanout"},
       "original": {"train": "3 plain, 2 lookalike_columns, 2 grain, 2 fanout, 1 of the other trap kinds",
                    "heldout": "1 plain, 1 lookalike_columns, 1 grain, 1 fanout, 1 of the other trap kinds"}}
AUTHOR = "claude full run (sonnet writers; opus solver and review)"
PATHS = (f"Let REPO={REPO}, DS={DS}, DOCS={DOCS}, PY={PY}, WORK={{work}} (use these as shell "
         "variables; the brief refers to them by name).")
ALONE = "Work on your own: do not start other agents."


def run(cmd, **kw):
    env = {**os.environ, "NL2SQL_DATASET_DIR": str(DS)}
    return subprocess.run(cmd, cwd=REPO / "nl2sql-v2", env=env, capture_output=True, text=True, **kw)


def plan(a):
    if a.copy:  # a new wave on the same databases: "fw:hw" adds hw01.. with fw01..'s databases
        old, new = a.copy.split(":")
        writers = json.loads((RUN / "plan.json").read_text())
        writers.update({new + w[len(old):]: v for w, v in list(writers.items()) if w.startswith(old)})
        (RUN / "plan.json").write_text(json.dumps(writers, indent=1))
        print({w: v["dbs"] for w, v in writers.items() if w.startswith(new)})
        return
    split = json.loads((DS / "db_split.json").read_text())
    train = sorted(d for d in split["train"] if d not in DONE)
    held = sorted(split["heldout"])
    random.Random(0).shuffle(train)
    random.Random(1).shuffle(held)
    writers = {}
    for i in range(0, len(train), 2):
        writers[f"fw{len(writers) + 1:02d}"] = {"split": "train", "dbs": train[i:i + 2]}
    for i in range(0, len(held), 3):
        writers[f"fw{len(writers) + 1:02d}"] = {"split": "heldout", "dbs": held[i:i + 3]}
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "plan.json").write_text(json.dumps(writers, indent=1))
    print({w: v["dbs"] for w, v in writers.items()})


def setup(a):
    writers = json.loads((RUN / "plan.json").read_text())
    qs = [json.loads(line) for line in (DS / "questions.jsonl").open()]
    for w in a.ids.split(","):
        work = RUN / w
        (work / "tmp").mkdir(parents=True, exist_ok=True)
        dbs, split = writers[w]["dbs"], writers[w]["split"]
        for db in dbs:
            if not (DS / "databases" / f"{db}.sqlite").exists():
                raise SystemExit(f"{db}: no database at {DS}/databases")
            lines = [q["question"].replace("\n", " ") for q in qs if q["db"] == db]
            (work / f"existing_{db}.txt").write_text("\n".join(lines) + "\n")
        n = 10 if split == "train" else 5
        print(f"===== {w}\nRead {REPO}/nl2sql-v2/scripts/question_briefs/writer.md and follow it.\n\n"
              f"Writer id W={w}. " + PATHS.format(work=work) + "\n\n"
              f"Databases: {', '.join(dbs)}. For each, write {n} items: {MIX[a.mix][split]}.\n\n{ALONE}\n")


def solve(a):
    for w in a.ids.split(","):
        items = [json.loads(line) for line in (RUN / w / "items.jsonl").open()]
        work = RUN / f"{w}s"
        (work / "tmp").mkdir(parents=True, exist_ok=True)
        with (work / "questions.jsonl").open("w") as f:
            for it in items:
                f.write(json.dumps({"id": it["id"], "db": it["db"], "question": it["question"]}) + "\n")
        print(f"===== {w}s\nRead {REPO}/nl2sql-v2/scripts/question_briefs/solver.md and follow it.\n\n"
              + PATHS.format(work=work) + f" QUESTIONS={work}/questions.jsonl, OUT={work}/solutions.jsonl.\n\n"
              f"There are {len(items)} questions, on {', '.join(sorted({it['db'] for it in items}))}.\n\n{ALONE}\n")


def validate(a):
    """Blind-solve comparison, stress test on altered copies, and review packets for disputes."""
    w = a.writer
    rv, items, sols = RUN / "review" / w, str(RUN / w / "items.jsonl"), str(RUN / f"{w}s" / "solutions.jsonl")
    rv.mkdir(parents=True, exist_ok=True)
    steps = [
        [str(PY), "scripts/validate_trap_items.py", "--items", items, "--solutions", sols, "--rounding-check",
         "--report", str(rv / "solve.report.json")],
        [str(PY), "scripts/stress_test_items.py", "--items", items, "--solutions", sols,
         "--output", str(rv / "stress.jsonl")],
        [str(PY), "scripts/review_packets.py", "--items", items, "--solutions", sols,
         "--reports", str(rv / "solve.report.json"), "--stress", str(rv / "stress.jsonl"),
         "--output", str(rv / "packets.jsonl")],
    ]
    for cmd in steps:
        res = run(cmd)
        (rv / f"{Path(cmd[1]).stem}.log").write_text(res.stdout + res.stderr)
        print("\n".join((res.stdout + res.stderr).strip().splitlines()[-2:]))
    print(f"packets: {sum(1 for _ in open(rv / 'packets.jsonl'))}")


def admit(a):
    """Reviewer fixes (gold_wrong with fixed_sql) go in as replacement items listed first, with a
    gold_right override; ambiguous and unfixed gold_wrong items are rejected."""
    out = RUN / "review" / f"admit_{'_'.join(a.writers)}"
    out.mkdir(parents=True, exist_ok=True)
    backup = RUN / f"questions_before_{'_'.join(a.writers)}.jsonl"
    backup.write_bytes((DS / "questions.jsonl").read_bytes())
    items = {it["id"]: it for w in a.writers for it in map(json.loads, open(RUN / w / "items.jsonl"))}
    reviews = [f for f in a.reviews.split(",") if f]
    final = {r["id"]: r for f in reviews for r in map(json.loads, open(f))}  # later files override
    fixed = 0
    with open(out / "fixed_items.jsonl", "w") as fi, open(out / "reviews_fixed.jsonl", "w") as fr:
        for r in final.values():
            if r["id"] in items and r["verdict"] == "gold_wrong" and r.get("fixed_sql"):
                it = dict(items[r["id"]], gold_sql=r["fixed_sql"], fixed_by_review=r["note"][:300])
                fi.write(json.dumps(it) + "\n")
                fr.write(json.dumps({"id": it["id"], "verdict": "gold_right",
                                     "note": "gold replaced by the reviewer's fix"}) + "\n")
                fixed += 1
    print(f"{len(items)} items from {a.writers}; {fixed} with the reviewer's fixed gold")
    cmd = [str(PY), "scripts/validate_trap_items.py",
           "--items", ",".join([str(out / "fixed_items.jsonl")] + [str(RUN / w / "items.jsonl") for w in a.writers]),
           "--solutions", ",".join(str(RUN / f"{w}s" / "solutions.jsonl") for w in a.writers),
           "--stress", ",".join(str(RUN / "review" / w / "stress.jsonl") for w in a.writers),
           "--rounding-check", "--write", "--author", AUTHOR, "--report", str(out / "admit.report.json")]
    if reviews:
        cmd += ["--reviews", ",".join(reviews + [str(out / "reviews_fixed.jsonl")])]
    res = run(cmd)
    print("\n".join(line for line in (res.stdout + res.stderr).splitlines() if ": PASS" not in line)[-1500:])
    qs = [json.loads(line) for line in open(DS / "questions.jsonl")]
    print(f"dataset: {len(qs)} {dict(Counter(q.get('source') for q in qs))} (backup {backup})")


def sync(a):
    """Push questions, gold, documents and trap items to Babel's bird_plat. Refuses unless Babel's
    questions.jsonl is a prefix of the local one (items are only appended here; questions written on
    Babel since the pull would otherwise be lost)."""
    srun = f"srun --jobid={a.job} --overlap -n1"
    remote = subprocess.run(["ssh", "babel", f"{srun} cat /data/user_data/$USER/judge-data/bird_plat/questions.jsonl"],
                            capture_output=True, check=True).stdout
    local = (DS / "questions.jsonl").read_bytes()
    if not local.startswith(remote):
        raise SystemExit(f"Babel's questions.jsonl ({remote.count(b'\n')} lines, md5 "
                         f"{hashlib.md5(remote).hexdigest()[:8]}) is not a prefix of the local one; pull first")
    files = ["bird_plat/questions.jsonl", "bird_plat/gold", "bird_plat/documents", "bird_plat/traps/items",
             "bird_plat/db_split.json"]
    tar = subprocess.Popen(["tar", "--no-mac-metadata", "--no-xattrs", "-czf", "-", "-C", str(ROOT), *files],
                           stdout=subprocess.PIPE, env={**os.environ, "COPYFILE_DISABLE": "1"})
    subprocess.run(["ssh", "babel", "rm -rf ~/judge-data-sync/bird_plat && mkdir -p ~/judge-data-sync && "
                    "tar xzf - -C ~/judge-data-sync"], stdin=tar.stdout, check=True)
    tar.wait()
    subprocess.run(["ssh", "babel", f"{srun} rsync -a ~/judge-data-sync/bird_plat/ "
                    "/data/user_data/$USER/judge-data/bird_plat/"], check=True)
    print(f"synced {local.count(b'\n')} questions ({local.count(b'\n') - remote.count(b'\n')} new) to Babel")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--copy", help="old:new writer prefix, e.g. fw:hw")
    p.set_defaults(f=plan)
    p = sub.add_parser("setup")
    p.add_argument("ids")
    p.add_argument("--mix", choices=MIX, default="hard")
    p.set_defaults(f=setup)
    p = sub.add_parser("solve")
    p.add_argument("ids")
    p.set_defaults(f=solve)
    p = sub.add_parser("validate")
    p.add_argument("writer")
    p.set_defaults(f=validate)
    p = sub.add_parser("admit")
    p.add_argument("writers", nargs="+")
    p.add_argument("--reviews", default="")
    p.set_defaults(f=admit)
    p = sub.add_parser("sync")
    p.add_argument("--job", required=True, help="a running Babel job with /data mounted")
    p.set_defaults(f=sync)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
