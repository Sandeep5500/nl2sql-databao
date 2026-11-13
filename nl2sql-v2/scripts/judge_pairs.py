#!/usr/bin/env python3
"""Measure a judge's pairwise accuracy on (correct, wrong) answer pairs harvested
from stored runs, instead of end-to-end selection over one 4-lane pool.

build: execute every stored episode's submitted SQL, cluster identical results per
       question (same equivalence as select_answer.py), label each cluster with the
       scorer, and write one JSON line per question. CPU only, needs the SQLite DBs.
judge: for each question with both a correct and a wrong cluster, sample up to
       --max-pairs (correct, wrong) pairs and ask the judge about each in both
       presentation orders. Rows are appended as they finish; --resume skips done ones.

Usage (from nl2sql-v2/):
    uv run python scripts/judge_pairs.py build --traces '../logs/traces/*' \\
        --output ../results/pairs/clusters.jsonl
    uv run python scripts/judge_pairs.py judge --clusters ../results/pairs/clusters.jsonl \\
        --judge-endpoint http://node:8765/v1 --judge-model Qwen/Qwen3.5-9B \\
        --mode pairwise --output ../results/pairs/judge_qwen9b_pairwise.csv --resume
"""

import argparse
import csv
import glob
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nl2sql.config import QUESTIONS_FILE, SQLITE_DIR
from nl2sql.db import Database
from nl2sql.eval import load_eval_standards, score_against_gold
from select_answer import (canonical, equivalent, pairwise_verdict, probe_pick,
                           question_context, result_preview)

FIELDS = ["instance_id", "pair", "correct_sql_id", "wrong_sql_id", "correct_first",
          "verdict", "judge_correct", "p_correct", "reason", "probe_sql", "error"]


class JevJudge:
    """System 1 decisions from an autotrust/JEV-* checkpoint served by plain vLLM
    (--enable-lora --lora-modules jev-decision=<dir>/adapter_vllm
    --logprobs-mode processed_logprobs): the option tokens' logprobs plus the bundled
    decision-head bias and per-kind temperature give calibrated probabilities."""

    def __init__(self, endpoint, jev_dir, max_state_chars):
        import httpx
        self.url = endpoint.rstrip("/").removesuffix("/v1") + "/v1/completions"
        self.dh = json.load(open(Path(jev_dir) / "adapter_vllm/decision_head.json"))
        self.temp = json.load(open(Path(jev_dir) / "calibration.json"))["per_kind"]
        self.max_state_chars = max_state_chars
        self.http = httpx.Client(timeout=600)

    def decide(self, kind, state, question, options=None):
        import math
        options = {"noul": ["false", "true"]}.get(kind, options)
        lines = options if kind != "choice" else [f"{'ABCDEFGHIJKLMNOP'[i]}) {o}"
                                                  for i, o in enumerate(options)]
        if len(state) > self.max_state_chars:  # jev_state caps each part; this is a backstop
            state = state[:self.max_state_chars] + "\n[truncated]"
        prompt = (f"[kind] {kind}\n[state] {state}\n[question] {question}\n[options]\n"
                  + "\n".join(lines) + "\n[decision]:")
        s = self.dh["slots"]["ranges"][kind][0]
        ids = self.dh["verbalizer_ids"][s:s + len(options)]
        r = self.http.post(self.url, json={
            "model": "jev-decision", "prompt": prompt, "max_tokens": 1, "temperature": 1.0,
            "top_k": 0, "top_p": 1.0, "logprobs": len(options), "allowed_token_ids": ids,
            "add_special_tokens": False, "return_tokens_as_token_ids": True}).json()
        lp = {int(k.split(":")[1]): v
              for k, v in r["choices"][0]["logprobs"]["top_logprobs"][0].items()}
        z = [(lp.get(t, -1e9) + self.dh["bias"][s + i]) / self.temp[kind]
             for i, t in enumerate(ids)]
        e = [math.exp(x - max(z)) for x in z]
        return [x / sum(e) for x in e]


def jev_state(q, doc, schema, cands, inputs="sql_results", db_context=""):
    """Decision state: question first (never truncated), then docs, schema, optional
    DB context, and each candidate capped separately. inputs picks what the judge
    sees of a candidate: sql_results (default), sql, results."""
    parts = [f"Database question: {q['question']}", doc.strip()[:3000], schema.strip()[:6000],
             db_context.strip()[:8000]]
    for n, (sql, res) in enumerate(cands):
        label = f"Candidate {'AB'[n]}" if len(cands) > 1 else "Candidate"
        block = []
        if inputs in ("sql_results", "sql"):
            block.append(f"{label} SQL:\n{sql[:4000]}")
        if inputs in ("sql_results", "results"):
            block.append(f"{label} execution result:\n{res[:3000]}")
        parts.append("\n".join(block))
    return "\n\n".join(p for p in parts if p)


_desc_cache = {}


DUP_FACT = None


def db_context_for(db, dbn, sqls, drop_dup_facts=False):
    """describe_table output (with the context engine's keys, profiles and notes,
    as the agent sees it) for every table the candidate SQLs mention.
    drop_dup_facts removes lines about duplicate/identical rows ('no key: N rows are
    exact copies ...'): those push a judge to de-duplicate where the benchmark
    counts every row."""
    global DUP_FACT
    import re as _re
    if DUP_FACT is None:
        DUP_FACT = _re.compile(r"exact cop|duplicate|identical rows|repeated rows|copies of",
                               _re.IGNORECASE)
    import re
    from nl2sql.config import DCE_PROJECT_DIR
    from nl2sql.context import TableContext
    from run_benchmark import resolve_datasource
    if ("ctx", dbn) not in _desc_cache:
        ds = resolve_datasource(dbn)
        try:
            _desc_cache[("ctx", dbn)] = TableContext(DCE_PROJECT_DIR, ds, explored=True) if ds else None
        except Exception:
            _desc_cache[("ctx", dbn)] = None
    text = " ".join(sqls).lower()
    out = []
    for t in db.list_tables() + db.list_views():
        if re.search(rf"\b{re.escape(t.lower())}\b", text):
            key = (dbn, t)
            if key not in _desc_cache:
                try:
                    _desc_cache[key] = db.describe_table(t, sample_rows=3,
                                                         context=_desc_cache[("ctx", dbn)])[:2500]
                except Exception as e:
                    _desc_cache[key] = f"{t}: describe failed ({str(e)[:80]})"
            out.append(_desc_cache[key])
    if drop_dup_facts:
        out = ["\n".join(l for l in block.splitlines() if not DUP_FACT.search(l)) for block in out]
    return "Context for the tables these queries use:\n" + "\n\n".join(out) if out else ""


def build(args):
    qmeta = {json.loads(l)["instance_id"]: json.loads(l) for l in open(QUESTIONS_FILE)}
    standards = load_eval_standards()
    episodes = defaultdict(list)  # iid -> [(run, sql)]
    for pattern in args.traces.split(","):
        for run_dir in sorted(glob.glob(pattern)):
            for f in sorted(glob.glob(f"{run_dir}/*.json")):
                try:
                    t = json.load(open(f))
                except Exception:
                    continue
                iid, sql = t.get("instance_id"), (t.get("sql") or "").strip()
                if iid in qmeta and iid.startswith("local") and sql:
                    episodes[iid].append((Path(run_dir).name, sql))
    print(f"{sum(map(len, episodes.values()))} episodes over {len(episodes)} questions")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    db_cache = {}
    with open(args.output, "w") as out:
        for iid in sorted(episodes):
            dbn = qmeta[iid]["db"]
            if dbn not in db_cache:
                db_cache[dbn] = Database(SQLITE_DIR / f"{dbn}.sqlite")
            db = db_cache[dbn]
            ignore_order = True  # never consult the gold file's ignore_order flag
            results, n_err = {}, 0  # sql -> canonical df (each distinct sql runs once)
            for _, sql in episodes[iid]:
                if sql in results:
                    continue
                try:
                    df, _ = db.query_preview(sql, 1, 5000, timeout_s=60)
                    results[sql] = canonical(df)
                except Exception:
                    results[sql] = None
                    n_err += 1
            clusters = []
            for run, sql in episodes[iid]:
                df = results[sql]
                if df is None:
                    continue
                for cl in clusters:
                    if equivalent(df, cl["df"], ignore_order):
                        cl["runs"].append(run)
                        if len(sql) < len(cl["sql"]):
                            cl["sql"] = sql  # keep simplest representative
                        break
                else:
                    clusters.append({"df": df, "sql": sql, "runs": [run]})
            for k, cl in enumerate(clusters):
                cl["id"] = k
                cl["correct"] = score_against_gold(cl["df"], iid, standards)[0]
                cl["preview"] = result_preview(cl.pop("df"))
            out.write(json.dumps({"instance_id": iid, "n_episodes": len(episodes[iid]),
                                  "n_exec_errors": n_err, "clusters": clusters}) + "\n")
            n_ok = sum(c["correct"] for c in clusters)
            print(f"{iid}: {len(episodes[iid])} episodes -> {len(clusters)} clusters "
                  f"({n_ok} correct), {n_err} exec errors", flush=True)
    for db in db_cache.values():
        db.close()


def in_shard(i, shard):
    """shard 'k/n' keeps every n-th item starting at k (None keeps all)."""
    if not shard:
        return True
    k, n = map(int, shard.split("/"))
    return i % n == k


def judge(args):
    import select_answer
    select_answer.THINKING = args.thinking
    from openai import OpenAI
    qmeta = {json.loads(l)["instance_id"]: json.loads(l) for l in open(QUESTIONS_FILE)}
    client = OpenAI(base_url=args.judge_endpoint, api_key="EMPTY", timeout=600)
    jud = (client, args.judge_model, args.max_tokens)
    jev = (JevJudge(args.judge_endpoint, args.jev_dir, args.jev_max_state_chars)
           if args.mode.startswith("jev") else None)
    noul_cache = {}  # (iid, cluster id) -> P(correct); jev_noul scores each answer alone

    done = set()
    if args.resume and Path(args.output).exists():
        done = {(r["pair"], r["correct_first"]) for r in csv.DictReader(open(args.output))}
    new_file = not Path(args.output).exists() or not done
    out = open(args.output, "w" if new_file else "a", newline="")
    w = csv.DictWriter(out, fieldnames=FIELDS)
    if new_file:
        w.writeheader()

    db_cache = {}
    for qi, line in enumerate(open(args.clusters)):
        if not in_shard(qi, args.shard):
            continue
        item = json.loads(line)
        iid = item["instance_id"]
        good = [c for c in item["clusters"] if c["correct"]]
        bad = [c for c in item["clusters"] if not c["correct"]]
        if not good or not bad:
            continue
        pairs = [(g, b) for g in good for b in bad]
        random.Random(iid).shuffle(pairs)
        pairs = pairs[:args.max_pairs]
        q = qmeta[iid]
        if q["db"] not in db_cache:
            db_cache[q["db"]] = Database(SQLITE_DIR / f"{q['db']}.sqlite")
        db = db_cache[q["db"]]
        doc, schema = question_context(q, db)
        for g, b in pairs:
            pair = f"{iid}:{g['id']}:{b['id']}"
            for correct_first in (1, 0):
                if (pair, str(correct_first)) in done:
                    continue
                first, second = ((g, b) if correct_first else (b, g))
                cands = [(first["sql"], first["preview"]), (second["sql"], second["preview"])]
                row = {"instance_id": iid, "pair": pair, "correct_sql_id": g["id"],
                       "wrong_sql_id": b["id"], "correct_first": correct_first,
                       "verdict": "", "judge_correct": "", "p_correct": "", "reason": "",
                       "probe_sql": "", "error": ""}
                try:
                    p_first = None
                    if args.mode == "pairwise":
                        v, p_first = pairwise_verdict(*jud, q, doc, schema, *cands)
                    elif args.mode == "jev_choice":
                        ctx = (db_context_for(db, q["db"], [first["sql"], second["sql"]],
                                              drop_dup_facts=args.jev_inputs.endswith("_nodup"))
                               if "_db" in args.jev_inputs else "")
                        p = jev.decide("choice", jev_state(
                                           q, doc, schema, cands,
                                           inputs=args.jev_inputs.split("_db")[0],
                                           db_context=ctx),
                                       "Which candidate SQL query correctly answers the "
                                       "database question?", ["Candidate A", "Candidate B"])
                        v = "AB"[p[1] > p[0]]
                        row["p_correct"] = round(p[0] if correct_first else p[1], 4)
                    elif args.mode == "jev_noul":
                        ps = []
                        for c in (first, second):
                            key = (iid, c["id"])
                            if key not in noul_cache:
                                noul_cache[key] = jev.decide(
                                    "noul", jev_state(q, doc, schema, [(c["sql"], c["preview"])]),
                                    "Does this SQL query's result correctly answer the "
                                    "database question?")[1]
                            ps.append(noul_cache[key])
                        v = "AB"[ps[1] > ps[0]]
                        row["p_correct"] = round(ps[0] if correct_first else ps[1], 4)
                        row["reason"] = f"P(true) A={ps[0]:.3f} B={ps[1]:.3f}"
                    else:
                        pos, row["reason"], row["probe_sql"], p_first = probe_pick(
                            *jud, q, doc, schema, db, cands)
                        v = "AB"[pos]
                    if p_first is not None:  # LLM judges: P(first shown) from logprobs
                        row["p_correct"] = round(p_first if correct_first else 1 - p_first, 4)
                    row["verdict"] = v
                    row["judge_correct"] = int((v == "A") == bool(correct_first))
                except Exception as e:
                    row["error"] = str(e)[:200]
                w.writerow(row)
                out.flush()
        print(f"{iid}: {len(pairs)} pairs", flush=True)
    out.close()
    for db in db_cache.values():
        db.close()
    summarize(args.output)


def aggregate(path):
    """Compare ways of turning the two orders (AB, BA) of each pair into one decision,
    over pairs judged in both orders. Each rule scores 1 / 0 per pair, ties 0.5."""
    rows = [r for r in csv.DictReader(open(path)) if r["judge_correct"] != ""]
    pairs = defaultdict(dict)
    for r in rows:
        pairs[r["pair"]][r["correct_first"]] = r
    both = {k: v for k, v in pairs.items() if len(v) == 2}
    if not both:
        return
    rules = defaultdict(dict)  # rule -> pair -> score
    decided = 0
    for k, p in both.items():
        ab, ba = int(p["1"]["judge_correct"]), int(p["0"]["judge_correct"])
        rules["single order, correct 1st"][k] = ab
        rules["count wins (tie -> coin)"][k] = (ab + ba) / 2
        rules["must agree (else abstain)"][k] = ab if ab == ba else None
        decided += ab == ba
        pc = [p[o].get("p_correct", "") for o in ("1", "0")]
        if all(x not in ("", None) for x in pc):
            m = (float(pc[0]) + float(pc[1])) / 2
            rules["average probability"][k] = 1.0 if m > 0.5 else 0.0 if m < 0.5 else 0.5
    print(f"--- aggregation over {len(both)} pairs judged both orders")
    for rule, sc in rules.items():
        vals = [v for v in sc.values() if v is not None]
        byq = defaultdict(list)
        for k, v in sc.items():
            if v is not None:
                byq[k.split(":")[0]].append(v)
        macro = sum(sum(v) / len(v) for v in byq.values()) / max(len(byq), 1)
        cov = f"  (decides {100 * len(vals) / len(sc):.0f}% of pairs)" if len(vals) < len(sc) else ""
        print(f"{rule:28s} {100 * sum(vals) / max(len(vals), 1):5.1f}%  "
              f"per-question {100 * macro:5.1f}%  n={len(vals)}{cov}")


def summarize(path):
    rows = list(csv.DictReader(open(path)))
    ok = [r for r in rows if r["judge_correct"] != ""]
    if not ok:
        print("no judged rows")
        return
    acc = sum(int(r["judge_correct"]) for r in ok) / len(ok)
    byq = defaultdict(list)
    for r in ok:
        byq[r["instance_id"]].append(int(r["judge_correct"]))
    macro = sum(sum(v) / len(v) for v in byq.values()) / len(byq)
    first = [int(r["judge_correct"]) for r in ok if r["correct_first"] == "1"]
    second = [int(r["judge_correct"]) for r in ok if r["correct_first"] == "0"]
    picks_a = sum(r["verdict"] == "A" for r in ok) / len(ok)
    pairs = defaultdict(dict)
    for r in ok:
        pairs[r["pair"]][r["correct_first"]] = int(r["judge_correct"])
    both = [p for p in pairs.values() if len(p) == 2]
    print(f"\n=== {path}")
    print(f"judged {len(ok)} of {len(rows)} calls ({len(rows) - len(ok)} failed), "
          f"{len(pairs)} pairs over {len(byq)} questions")
    print(f"accuracy {100 * acc:.1f}%  (per-question macro {100 * macro:.1f}%; chance 50%)")
    print(f"correct shown first {100 * sum(first) / max(len(first), 1):.1f}%  "
          f"shown second {100 * sum(second) / max(len(second), 1):.1f}%  "
          f"(picks A {100 * picks_a:.1f}% of the time)")
    if both:
        print(f"pairs judged both orders: {len(both)} | right both "
              f"{100 * sum(p['1'] and p['0'] for p in both) / len(both):.1f}%  wrong both "
              f"{100 * sum(not p['1'] and not p['0'] for p in both) / len(both):.1f}%  "
              f"split (order decided) "
              f"{100 * sum(p['1'] != p['0'] for p in both) / len(both):.1f}%")
    aggregate(path)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--traces", required=True,
                   help="comma-separated globs of trace directories")
    b.add_argument("--output", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--clusters", required=True)
    j.add_argument("--judge-endpoint", required=True)
    j.add_argument("--judge-model", required=True)
    j.add_argument("--mode", choices=["pairwise", "probe", "jev_choice", "jev_noul"],
                   default="pairwise",
                   help="pairwise = select_answer's DivSkill prompt; probe = the judge "
                        "writes and runs one SQL check before deciding; jev_choice = a "
                        "JEV checkpoint's calibrated A/B choice; jev_noul = JEV's P(correct) "
                        "for each answer alone, higher one wins (order-free)")
    j.add_argument("--jev-dir", help="local autotrust/JEV-* snapshot (decision_head.json, "
                                     "calibration.json) for the jev_* modes")
    j.add_argument("--jev-max-state-chars", type=int, default=40000)
    j.add_argument("--jev-inputs", default="sql_results",
                   choices=["sql_results", "sql", "results", "sql_results_db",
                            "sql_results_db_nodup"],
                   help="what jev_choice shows of each candidate; sql_results_db adds "
                        "describe_table context for the tables the two queries use; "
                        "sql_results_db_nodup drops its duplicate-row facts")
    j.add_argument("--max-pairs", type=int, default=12,
                   help="(correct, wrong) pairs sampled per question")
    j.add_argument("--max-tokens", type=int, default=2048)
    j.add_argument("--output", required=True)
    j.add_argument("--resume", action="store_true")
    j.add_argument("--thinking", action="store_true",
                   help="LLM judges reason before answering (Qwen enable_thinking, temp 0.6)")
    j.add_argument("--shard", help="k/n: judge only every n-th question starting at k "
                                   "(run n processes in parallel, one output file each)")
    s = sub.add_parser("summary")
    s.add_argument("outputs", nargs="+")
    args = ap.parse_args()
    if args.cmd == "build":
        build(args)
    elif args.cmd == "judge":
        judge(args)
    else:
        for p in args.outputs:
            summarize(p)


if __name__ == "__main__":
    main()
