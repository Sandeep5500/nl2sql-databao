#!/usr/bin/env python3
"""Best-of-K selection over completed runs: dedupe candidates by execution
result, majority-vote, and let a judge model pick among the distinct clusters
(DivSkill-style dedup+judge).

Usage (from nl2sql-v2/):
    uv run python scripts/select_answer.py \
        --runs ../results/q36_pass4_k1.csv,../results/q36_pass4_k2.csv,... \
        --judge-endpoint http://node:8765/v1 --judge-model QuantTrio/... \
        --output ../results/q36_selected.csv
Reports: per-lane avg, majority-only, judge-only, and hybrid selection scores.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from openai import OpenAI

from nl2sql.config import DOCS_DIR, QUESTIONS_FILE, SQLITE_DIR
from nl2sql.db import Database
from nl2sql.eval import _csv_roundtrip, compare_dataframes, load_eval_standards, \
    score_against_gold

PAIRWISE_PROMPT = """You are judging two candidate SQL answers to a database question.

Question: {question}
{doc_section}{schema_section}
--- Candidate A ---
SQL:
{sql_a}
Execution result:
{res_a}

--- Candidate B ---
SQL:
{sql_b}
Execution result:
{res_b}

Which candidate correctly answers the question? Weigh: does the SQL's logic match the \
question's intent (filters, aggregation level, ranking direction)? Does the result's \
shape match what was asked (columns, granularity)? Do the values look plausible?

Reply with JSON only: {{"winner": "A" or "B", "reason": "<one sentence>"}}"""

JUDGE_PROMPT = """You are judging candidate SQL answers to a database question. \
Multiple independent attempts produced the candidates below; identical execution \
results were merged, and `votes` counts how many attempts produced that result.

Question: {question}
{doc_section}{schema_section}
Candidates:
{candidates}

Judge which candidate correctly answers the question. Weigh: does the SQL's logic \
match the question's intent (filters, aggregation level, ranking direction)? Does the \
result's shape match what was asked (columns, granularity)? Do the values look \
plausible? Higher votes means more attempts agreed, which is weak evidence of \
correctness — override it when the logic is wrong.

Reply with JSON only: {{"winner": <candidate number>, "reason": "<one sentence>"}}"""


def canonical(df):
    """Cluster key helper: normalized via the same CSV round-trip as scoring."""
    return _csv_roundtrip(df)


def equivalent(a, b, ignore_order):
    if a.shape[0] != b.shape[0]:
        return False
    return compare_dataframes(a, b, ignore_order=ignore_order) and \
        compare_dataframes(b, a, ignore_order=ignore_order)


def result_preview(df, rows=8):
    body = df.head(rows).to_csv(index=False)
    extra = f"[{len(df)} rows x {len(df.columns)} cols total]"
    return body + extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated result CSVs")
    ap.add_argument("--judge-endpoint", required=True)
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--schema-overview", action="store_true", default=True)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--mode", choices=["pairwise", "single"], default="pairwise",
                    help="pairwise = DivSkill-faithful round-robin (no vote counts "
                         "shown, temp 0.2, both presentation orders); single = one "
                         "pick-best-of-N call with vote counts shown")
    args = ap.parse_args()

    run_files = args.runs.split(",")
    runs = [{r["instance_id"]: r for r in csv.DictReader(open(f))} for f in run_files]
    qmeta = {json.loads(l)["instance_id"]: json.loads(l) for l in open(QUESTIONS_FILE)}
    standards = load_eval_standards()
    client = OpenAI(base_url=args.judge_endpoint, api_key="EMPTY", timeout=300)

    ids = sorted(set.intersection(*(set(r) for r in runs)))
    db_cache = {}
    tallies = {"lane_avg": 0.0, "majority": 0, "judge": 0, "oracle_any": 0}
    out_rows = []

    for iid in ids:
        q = qmeta[iid]
        dbn = q["db"]
        if dbn not in db_cache:
            db_cache[dbn] = Database(SQLITE_DIR / f"{dbn}.sqlite")
        db = db_cache[dbn]
        ignore_order = standards.get(iid, {}).get("ignore_order", False)

        # gather + execute candidates
        cands = []
        for li, run in enumerate(runs):
            sql = (run[iid].get("sql") or "").replace("\\n", "\n")
            if not sql.strip():
                continue
            try:
                df, _ = db.query_preview(sql, 1, 5000, timeout_s=60)
                cands.append({"lane": li, "sql": sql, "df": canonical(df)})
            except Exception:
                continue
        tallies["lane_avg"] += sum(
            int(run[iid]["score"]) for run in runs) / len(runs)

        if not cands:
            out_rows.append({"instance_id": iid, "n_clusters": 0, "picked": "",
                             "majority_score": 0, "judge_score": 0, "judge_reason": ""})
            continue

        # dedupe into clusters by execution-result equivalence
        clusters = []
        for c in cands:
            for cl in clusters:
                if equivalent(c["df"], cl["df"], ignore_order):
                    cl["votes"] += 1
                    if len(c["sql"]) < len(cl["sql"]):
                        cl["sql"] = c["sql"]  # keep simplest representative
                    break
            else:
                clusters.append({"df": c["df"], "sql": c["sql"], "votes": 1})
        clusters.sort(key=lambda cl: -cl["votes"])

        maj_score, _ = score_against_gold(clusters[0]["df"], iid, standards)
        any_score = max(score_against_gold(cl["df"], iid, standards)[0]
                        for cl in clusters)

        def ask(prompt, temp):
            resp = client.chat.completions.create(
                model=args.judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp, max_tokens=args.max_tokens,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}}
                if "qwen" in args.judge_model.lower() else None)
            text = re.sub(r"<think>.*?</think>", "",
                          resp.choices[0].message.content or "", flags=re.DOTALL)
            m = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(m.group(0)) if m else {}

        doc = ""
        if q.get("external_knowledge"):
            pth = DOCS_DIR / q["external_knowledge"]
            if pth.exists():
                doc = "\nReference documentation:\n" + pth.read_text()[:8000] + "\n"
        schema = ""
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from run_benchmark import schema_overview
            schema = "\n" + schema_overview(db) + "\n"
        except Exception:
            pass

        # judge among clusters (skip the call when there is nothing to decide)
        if len(clusters) == 1:
            pick, reason = 0, "single distinct result"
        elif args.mode == "pairwise":
            # DivSkill: exhaustive round-robin over unordered pairs, each judged
            # twice with swapped presentation order; highest win count wins.
            wins = [0] * len(clusters)
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    for (a, b) in ((i, j), (j, i)):
                        prompt = PAIRWISE_PROMPT.format(
                            question=q["question"], doc_section=doc,
                            schema_section=schema,
                            sql_a=clusters[a]["sql"], res_a=result_preview(clusters[a]["df"]),
                            sql_b=clusters[b]["sql"], res_b=result_preview(clusters[b]["df"]))
                        try:
                            v = str(ask(prompt, 0.2).get("winner", "")).strip().upper()
                            if v == "A": wins[a] += 1
                            elif v == "B": wins[b] += 1
                        except Exception:
                            pass
            pick = max(range(len(clusters)), key=lambda k: (wins[k], clusters[k]["votes"]))
            reason = f"round-robin wins={wins}"
        else:
            cand_txt = "\n\n".join(
                f"--- Candidate {i + 1} (votes: {cl['votes']}) ---\nSQL:\n{cl['sql']}\n"
                f"Execution result:\n{result_preview(cl['df'])}"
                for i, cl in enumerate(clusters))
            prompt = JUDGE_PROMPT.format(question=q["question"], doc_section=doc,
                                         schema_section=schema, candidates=cand_txt)
            try:
                data = ask(prompt, 0.2)
                pick = int(data.get("winner", 1)) - 1
                reason = str(data.get("reason", ""))[:200]
                if not 0 <= pick < len(clusters):
                    pick, reason = 0, "invalid pick -> majority fallback"
            except Exception as e:
                pick, reason = 0, f"judge error -> majority fallback: {str(e)[:80]}"

        judge_score, _ = score_against_gold(clusters[pick]["df"], iid, standards)
        tallies["majority"] += maj_score
        tallies["judge"] += judge_score
        tallies["oracle_any"] += any_score
        out_rows.append({"instance_id": iid, "n_clusters": len(clusters),
                         "picked": pick + 1, "majority_score": maj_score,
                         "judge_score": judge_score, "judge_reason": reason})
        print(f"{iid}: {len(cands)} cands -> {len(clusters)} clusters | "
              f"majority={maj_score} judge={judge_score} ({reason[:60]})", flush=True)

    for dbx in db_cache.values():
        dbx.close()

    n = len(ids)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n=== selection over {n} questions, {len(runs)} lanes ===")
    print(f"avg single lane : {tallies['lane_avg']:.1f} ({100 * tallies['lane_avg'] / n:.1f}%)")
    print(f"majority vote   : {tallies['majority']} ({100 * tallies['majority'] / n:.1f}%)")
    print(f"judge selection : {tallies['judge']} ({100 * tallies['judge'] / n:.1f}%)")
    print(f"oracle (any)    : {tallies['oracle_any']} ({100 * tallies['oracle_any'] / n:.1f}%)")


if __name__ == "__main__":
    main()
