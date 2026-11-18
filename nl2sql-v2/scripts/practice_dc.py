#!/usr/bin/env python3
"""Stage B step 1 of documents/head_probe_prereg.md: the practice judgments again with the deployed
diff_cmp prompt (judge_prompts.py). Same ordered pairs, candidates and previews as the stored
sample_judge_verdicts.py records; only the instructions differ, plus the result comparison.

prompts  Every paired group's SQL is re-run as the pools ran it (Database.query_preview(sql, 1, 5000,
         timeout 60 s), then canonical) and kept when it reproduces the stored group (same shape,
         every stored preview row present: build_compare_cache.reproduces). An ordered pair's
         comparison is compare_results(first, second) as build_compare_cache.py writes it, or
         "Comparison unavailable." when a side does not reproduce. The prompt is the stored one with
         the deployed instructions replaced by diff_cmp's. Records keep their pairs in order, so the
         pair label files still apply; samples are emptied. Needs the question set's
         NL2SQL_DATASET_DIR (bird_plat for train_v1, cplx and claude; beaver for beaver_p1).
judge    --samples per ordered pair with thinking at temperature 0.6 and 8192 tokens, as
         sample_judge_verdicts.py and rejudge_pools.py call the judge. Records are written in
         sample_judge_verdicts.py's format (extract_judge_states.py and probe_fit.py read them
         unchanged) once all their samples are back; records already in --output are skipped.
         One Slurm job judges a file at a time: the first to start it writes <output>.claim with its
         job id, and another job that finds the claim of a running job leaves the file to it.

    NL2SQL_DATASET_DIR=$D/bird_plat python scripts/practice_dc.py prompts \\
        --verdicts $R/judge_train/verdicts_train_v1.jsonl --out $P/judge_train/prompts_train_v1.jsonl
    python scripts/practice_dc.py judge --prompts $P/judge_train/prompts_train_v1.jsonl \\
        --judge-endpoint http://localhost:8765/v1,http://localhost:8766/v1 \\
        --judge-model QuantTrio/Qwen3.6-35B-A3B-AWQ --output $P/judge_train/verdicts_train_v1.jsonl --resume
"""

import argparse
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from select_answer import PAIRWISE_PROMPT  # noqa: E402
from judge_prompts import _HEAD, VARIANTS  # noqa: E402

BASE_TAIL = PAIRWISE_PROMPT[len(_HEAD):].format()  # the deployed instructions, as stored prompts end
DC_TAIL = VARIANTS["diff_cmp"]["template"][len(_HEAD):]  # still holds {comparison}
UNAVAILABLE = "Comparison unavailable."


def dc_prompt(stored, comparison):
    if not stored.endswith(BASE_TAIL):
        raise ValueError("stored prompt does not end with the deployed instructions")
    return stored[:-len(BASE_TAIL)] + DC_TAIL.format(comparison=comparison)


def prompts(args):
    from build_compare_cache import reproduces
    from nl2sql.config import SQLITE_DIR
    from nl2sql.db import Database
    from result_compare import compare_results
    from select_answer import canonical

    dbs, by_sql = {}, {}
    n_groups = n_bad = n_pairs = n_unavail = 0
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as out:
        for n, line in enumerate(open(args.verdicts)):
            if args.limit and n >= args.limit:
                break
            r = json.loads(line)
            full = {}
            for gi in sorted({i for p in r["pairs"] for i in (p["first"], p["second"])}):
                g = r["groups"][gi]
                sk = (r["db"], g["sql"])
                if sk not in by_sql:
                    if r["db"] not in dbs:
                        dbs[r["db"]] = Database(SQLITE_DIR / f"{r['db']}.sqlite")
                    try:
                        df, _ = dbs[r["db"]].query_preview(g["sql"], 1, 5000, timeout_s=60)
                        by_sql[sk] = canonical(df)
                    except Exception as ex:
                        print(f"{r['instance_id']} group {gi}: {str(ex)[:100]}", flush=True)
                        by_sql[sk] = None
                df = by_sql[sk]
                full[gi] = df if df is not None and reproduces(df, g) else None
                n_groups += 1
                n_bad += full[gi] is None
            for p in r["pairs"]:
                fa, fb = full[p["first"]], full[p["second"]]
                text = UNAVAILABLE if fa is None or fb is None else \
                    compare_results(fa, fb, fa.shape[0], fb.shape[0], capped=False)
                p["prompt"], p["samples"], p["comparison_available"] = dc_prompt(p["prompt"], text), [], text != UNAVAILABLE
                n_pairs += 1
                n_unavail += text == UNAVAILABLE
            out.write(json.dumps(r) + "\n")
    for d in dbs.values():
        d.close()
    print(f"{args.verdicts}: {n_groups} paired groups re-run ({n_bad} not reproduced), {n_pairs} ordered pairs "
          f"({n_unavail} without a comparison) -> {args.out}", flush=True)


def claim(output):
    """True when this job may judge output: no claim yet, its own (a requeued job keeps its id), or the
    claim of a job that is no longer running."""
    me = os.environ.get("SLURM_JOB_ID", "")
    path = Path(output + ".claim")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, me.encode())
        os.close(fd)
        return True
    except FileExistsError:
        owner = path.read_text().strip()
        if owner == me:
            return True
        try:
            running = subprocess.run(["squeue", "-h", "-j", owner, "-t", "RUNNING", "-o", "%i"],
                                     capture_output=True, text=True).stdout.strip()
        except FileNotFoundError:  # no Slurm here: the claim cannot be checked, so it stands
            running = owner
        if running:
            print(f"{output} is being judged by job {owner}; leaving it", flush=True)
            return False
        path.write_text(me)
        return True


def judge(args):
    import openai
    from sample_judge_verdicts import judge_once, verdict_of

    if not claim(args.output):
        return
    clients =[openai.OpenAI(base_url=e, api_key="EMPTY", timeout=1800) for e in args.judge_endpoint.split(",")]
    turn = itertools.count()
    done = set()
    if args.resume and Path(args.output).exists():
        done = {json.loads(l)["instance_id"] for l in open(args.output)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    records, tasks = {}, []
    for n, line in enumerate(open(args.prompts)):
        if args.limit and n >= args.limit:
            break
        r = json.loads(line)
        if r["instance_id"] in done:
            continue
        r["judge_model"], r["judge_prompt"] = args.judge_model, "diff_cmp"
        records[r["instance_id"]] = r
        tasks += [(r["instance_id"], pi) for pi in range(len(r["pairs"])) for _ in range(args.samples)]
    print(f"{len(records)} records to judge, {len(tasks)} judge calls", flush=True)

    remaining = defaultdict(int)
    for iid, _ in tasks:
        remaining[iid] += 1
    lock = threading.Lock()
    out = open(args.output, "a")
    for iid, r in records.items():  # questions with nothing to judge are written now
        if not remaining[iid]:
            out.write(json.dumps(r) + "\n")
    out.flush()

    def ask(prompt):
        start = next(turn)
        for attempt in itertools.count():
            client = clients[(start + attempt) % len(clients)]
            try:
                return judge_once(client, args.judge_model, prompt, args.max_tokens)
            except openai.APITimeoutError:  # the server answered too slowly: not a failover
                raise
            except (openai.APIConnectionError, openai.InternalServerError):
                if attempt + 1 >= 120 * len(clients):
                    raise
                if (attempt + 1) % len(clients) == 0:  # every server failed this round
                    time.sleep(60)

    def call(iid, pi):
        p = records[iid]["pairs"][pi]
        try:
            text, reasoning, truncated = ask(p["prompt"])
            v = verdict_of(text)
            return {"verdict": v, "right": v == p["correct_letter"], "answer": text.strip(),
                    "reasoning": reasoning, "truncated": truncated, "error": ""}
        except Exception as e:
            return {"verdict": None, "right": False, "answer": "", "reasoning": "",
                    "truncated": False, "error": str(e)[:200]}

    n_done = shown = 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(call, iid, pi): (iid, pi) for iid, pi in tasks}
        for fut in as_completed(futures):
            iid, pi = futures[fut]
            with lock:
                records[iid]["pairs"][pi]["samples"].append(fut.result())
                remaining[iid] -= 1
                n_done += 1
                if remaining[iid] == 0:
                    out.write(json.dumps(records[iid]) + "\n")
                    out.flush()
                if n_done - shown >= 200:
                    shown = n_done
                    print(f"[{n_done}/{len(tasks)}]", flush=True)
    out.close()
    print("done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompts")
    p.add_argument("--verdicts", required=True, help="a sample_judge_verdicts.py output")
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0, help="first N records only (smoke test)")
    j = sub.add_parser("judge")
    j.add_argument("--prompts", required=True, help="a prompts output")
    j.add_argument("--judge-endpoint", required=True, help="one or more, comma-separated")
    j.add_argument("--judge-model", required=True)
    j.add_argument("--samples", type=int, default=4)
    j.add_argument("--max-tokens", type=int, default=8192)
    j.add_argument("--workers", type=int, default=96)
    j.add_argument("--output", required=True)
    j.add_argument("--resume", action="store_true")
    j.add_argument("--limit", type=int, default=0, help="first N records only (smoke test)")
    args = ap.parse_args()
    prompts(args) if args.cmd == "prompts" else judge(args)


if __name__ == "__main__":
    main()
