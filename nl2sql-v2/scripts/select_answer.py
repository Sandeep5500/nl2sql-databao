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
import random
import re
import sys
import threading
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

PAIRWISE_NOTES_PROMPT = """You are judging two candidate SQL answers to a database question.

Question: {question}
{doc_section}{schema_section}
--- Candidate A ---
SQL:
{sql_a}
Execution result:
{res_a}
Notes from the agent that produced A (its own summary of how it got there; may be wrong):
{notes_a}

--- Candidate B ---
SQL:
{sql_b}
Execution result:
{res_b}
Notes from the agent that produced B (its own summary of how it got there; may be wrong):
{notes_b}

Which candidate correctly answers the question? Weigh: does the SQL's logic match the \
question's intent (filters, aggregation level, ranking direction)? Does the result's \
shape match what was asked (columns, granularity)? Do the values look plausible? Use the \
notes to see where the two interpretations differ, then decide from the question, the SQL \
and the results, not from how confident a note sounds.

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

PROBE_WRITE_PROMPT = """You are checking candidate SQL answers to a database question. \
Independent attempts produced the candidates below, and their results disagree.

Question: {question}
{doc_section}{schema_section}
Candidates:
{candidates}

Write ONE read-only SQL query (DuckDB syntax; the tables above are queryable) whose \
result would show which candidate is correct. Target the point where the candidates \
differ: e.g. whether a join duplicates rows, which values a filter column actually \
holds, whether ties exist at a cut-off, which grain the data is stored at.

Reply with one sentence saying what the query checks, then the query in a ```sql block."""

PROBE_JUDGE_PROMPT = """You are judging candidate SQL answers to a database question. \
Independent attempts produced the candidates below, and their results disagree.

Question: {question}
{doc_section}{schema_section}
Candidates:
{candidates}

To tell them apart, this check was run against the database:
{probe_note}
SQL:
{probe_sql}
Result:
{probe_result}

Using the check's result as evidence, judge which candidate correctly answers the \
question: filters, aggregation level, join duplication, ranking direction, output shape.

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


COMPARISON_UNAVAILABLE = "Comparison unavailable."  # as build_compare_cache.py writes it


def result_comparison(df_a, df_b):
    """Where two candidates' full results differ (result_compare.py), as the diff_cmp judge
    prompt shows it; built from the same canonical results build_compare_cache.py used."""
    try:
        from result_compare import compare_results
        return compare_results(df_a, df_b, df_a.shape[0], df_b.shape[0], capped=False)
    except Exception:
        return COMPARISON_UNAVAILABLE


THINKING = False  # judges reason before answering (Qwen enable_thinking); callers set it
LAST_REASONING = None  # the last reply's separate reasoning text (thinking mode), if any
_LOCAL = threading.local()  # the same, per thread (.reasoning), for callers judging in threads


def ask_text(client, model, prompt, temp, max_tokens, logprobs=False):
    """Reply text; with logprobs=True, (text, token logprobs with top-5 alternatives).
    With THINKING, Qwen-family judges reason first, at Qwen's recommended
    thinking-mode temperature (0.6: low temperatures make reasoning loop)."""
    qwen_like = any(k in model.lower() for k in ("qwen", "jev", "judge"))  # judge-*: our tuned Qwen judges
    think = THINKING and qwen_like
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=max(temp, 0.6) if think else temp, max_tokens=max_tokens,
        logprobs=logprobs or None, top_logprobs=5 if logprobs else None,
        extra_body={"chat_template_kwargs": {"enable_thinking": think}} if qwen_like else None)
    global LAST_REASONING
    msg = resp.choices[0].message
    extra = msg.model_dump() if hasattr(msg, "model_dump") else {}
    LAST_REASONING = _LOCAL.reasoning = (getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
                                         or extra.get("reasoning") or extra.get("reasoning_content"))
    text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.DOTALL)
    return (text, resp.choices[0].logprobs) if logprobs else text


def ask_json(client, model, prompt, temp, max_tokens, labels=None):
    """Raises when the reply holds no JSON object, so a judge that ignores the
    format shows up as an error instead of a silent default pick. With labels
    (e.g. ("A", "B")), returns (data, P(labels[0])) where the probability is read
    from the token that fills "winner" (None when it cannot be located)."""
    if labels:
        text, lp = ask_text(client, model, prompt, temp, max_tokens, logprobs=True)
    else:
        text, lp = ask_text(client, model, prompt, temp, max_tokens), None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in reply: {text[-120:]!r}")
    data = json.loads(m.group(0))
    return (data, winner_prob(lp, labels)) if labels else data


def winner_prob(lp, labels):
    """P(labels[0]) among labels at the token that fills the *last* '"winner": ...'
    in the reply (reasoning text may mention the key earlier), from that position's
    top logprobs (raw model probabilities)."""
    import math
    if lp is None or not getattr(lp, "content", None):
        return None
    seen, found = "", None
    for tok in lp.content:
        key = tok.token.strip(' "\'')
        if key in labels and '"winner"' in seen[-16:]:
            mass = dict.fromkeys(labels, 0.0)
            for alt in tok.top_logprobs or []:
                k = alt.token.strip(' "\'')
                if k in mass:
                    mass[k] += math.exp(alt.logprob)
            total = sum(mass.values())
            found = mass[labels[0]] / total if total > 0 else None
        seen += tok.token
    return found


def question_context(q, db):
    """(doc_section, schema_section) for judge prompts."""
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
    return doc, schema


def pairwise_verdict(client, model, max_tokens, q, doc, schema, a, b, notes=None, template=None,
                     comparison=None):
    """('A' or 'B', P(A) or None) for candidates a, b given as (sql, result preview).
    notes: optional (notes on A, notes on B) from the agents' traces.
    template: a judge_prompts.VARIANTS template instead of PAIRWISE_PROMPT; comparison: the
    result_compare text that fills a template's {comparison}."""
    fmt = dict(question=q["question"], doc_section=doc, schema_section=schema,
               sql_a=a[0], res_a=a[1], sql_b=b[0], res_b=b[1])
    if notes:
        prompt = PAIRWISE_NOTES_PROMPT.format(notes_a=notes[0], notes_b=notes[1], **fmt)
    elif template:
        if "{comparison}" in template:
            fmt["comparison"] = comparison or COMPARISON_UNAVAILABLE
        prompt = template.format(**fmt)
    else:
        prompt = PAIRWISE_PROMPT.format(**fmt)
    data, p_a = ask_json(client, model, prompt, 0.2, max_tokens, labels=("A", "B"))
    v = str(data.get("winner", "")).strip().upper()
    if v not in ("A", "B"):
        raise ValueError(f"invalid verdict {v!r}")
    return v, p_a


def probe_pick(client, model, max_tokens, q, doc, schema, db, cands):
    """The judge writes one SQL check that separates cands [(sql, result preview)],
    it is run on db, and the judge picks with its result.
    Returns (position in cands, reason, probe sql, P(first candidate) or None)."""
    cand_txt = "\n\n".join(f"--- Candidate {n + 1} ---\nSQL:\n{sql}\n"
                           f"Execution result:\n{res}" for n, (sql, res) in enumerate(cands))
    fmt = dict(question=q["question"], doc_section=doc, schema_section=schema,
               candidates=cand_txt)
    text = ask_text(client, model, PROBE_WRITE_PROMPT.format(**fmt), 0.2, max_tokens)
    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    psql = m.group(1).strip() if m else ""
    note = text[:m.start()].strip()[:300] if m else text.strip()[:300]
    try:
        pdf, _ = db.query_preview(psql, 1, 5000, timeout_s=60)
        presult = result_preview(pdf, rows=20)
    except Exception as e:
        presult = f"ERROR: {str(e)[:300]}"
    labels = tuple(str(n + 1) for n in range(len(cands)))
    data, p_first = ask_json(client, model, PROBE_JUDGE_PROMPT.format(
        probe_note=note, probe_sql=psql or "(none)", probe_result=presult, **fmt),
        0.2, max_tokens, labels=labels)
    pos = int(data.get("winner", 0)) - 1
    if not 0 <= pos < len(cands):
        raise ValueError(f"invalid pick {pos + 1}")
    return pos, str(data.get("reason", ""))[:200], psql, p_first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="comma-separated result CSVs")
    ap.add_argument("--judge-endpoint", required=True)
    ap.add_argument("--judge-model", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--schema-overview", action="store_true", default=True)
    ap.add_argument("--max-tokens", type=int, help="default 8192 with --thinking, else 2048")
    ap.add_argument("--thinking", action="store_true",
                    help="the judge reasons before answering (Qwen enable_thinking, temperature 0.6), "
                         "as in the selection evals")
    ap.add_argument("--judge-prompt", default="diff_cmp",
                    help="pairwise mode: a judge_prompts.VARIANTS name. diff_cmp (list the SQL "
                         "differences, check each against a computed comparison of the two full "
                         "results) was adopted on 2026-11-12 with --thinking and 8192 tokens "
                         "(documents/judge_prompt_eval.md); base is the earlier prompt")
    ap.add_argument("--mode", choices=["pairwise", "single", "probe", "pairwise_probe"], default="pairwise",
                    help="pairwise = DivSkill-faithful round-robin (no vote counts "
                         "shown, temp 0.2, both presentation orders); single = one "
                         "pick-best-of-N call with vote counts shown; probe = the judge "
                         "writes one SQL check that separates the candidates, it is run, "
                         "and the judge picks with its result (no vote counts shown); "
                         "pairwise_probe = pairwise round-robin where each ordered pair "
                         "gets its own SQL check")
    args = ap.parse_args()
    global THINKING
    THINKING = args.thinking
    if args.max_tokens is None:
        args.max_tokens = 8192 if args.thinking else 2048
    from judge_prompts import VARIANTS  # here, not at the top: judge_prompts imports this module
    if args.judge_prompt not in VARIANTS:
        raise SystemExit(f"unknown --judge-prompt {args.judge_prompt}; known: {', '.join(VARIANTS)}")
    template = VARIANTS[args.judge_prompt]["template"]
    if args.mode == "pairwise" and args.judge_prompt != "base" and not (args.thinking and args.max_tokens >= 8192):
        print(f"note: --judge-prompt {args.judge_prompt} was evaluated with --thinking and 8192 tokens",
              file=sys.stderr)

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
        ignore_order = True  # grouping must not consult the gold file's ignore_order flag

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
                             "majority_score": 0, "judge_score": 0, "judge_reason": "",
                             "probe_sql": ""})
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

        doc, schema = question_context(q, db)
        cand = [(cl["sql"], result_preview(cl["df"])) for cl in clusters]
        judge = (client, args.judge_model, args.max_tokens)

        def probe_judge(idxs):
            return probe_pick(*judge, q, doc, schema, db, [cand[i] for i in idxs])

        # judge among clusters (skip the call when there is nothing to decide)
        probe_sql = ""
        if len(clusters) == 1:
            pick, reason = 0, "single distinct result"
        elif args.mode == "probe":
            # clusters are sorted by votes; shuffle so position 1 is not the majority
            order = list(range(len(clusters)))
            random.Random(iid).shuffle(order)
            try:
                pos, reason, probe_sql, _ = probe_judge(order)
                pick = order[pos]
            except Exception as e:
                pick, reason = 0, f"judge error -> majority fallback: {str(e)[:80]}"
        elif args.mode == "pairwise_probe":
            # round-robin as in pairwise, but each ordered pair gets its own SQL check
            wins = [0] * len(clusters)
            n_probes = n_written = n_failed = 0
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    for (a, b) in ((i, j), (j, i)):
                        try:
                            pos, _, psql, _ = probe_judge([a, b])
                            wins[(a, b)[pos]] += 1
                            n_written += bool(psql)
                        except Exception:
                            n_failed += 1
                        n_probes += 1
            pick = max(range(len(clusters)), key=lambda k: (wins[k], clusters[k]["votes"]))
            reason = f"round-robin wins={wins} failed={n_failed}/{n_probes}"
            probe_sql = f"{n_written}/{n_probes} probes written"
        elif args.mode == "pairwise":
            # DivSkill: exhaustive round-robin over unordered pairs, each judged
            # twice with swapped presentation order; highest win count wins.
            wins = [0] * len(clusters)
            n_calls = n_failed = 0
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    for (a, b) in ((i, j), (j, i)):
                        n_calls += 1
                        cmp_text = (result_comparison(clusters[a]["df"], clusters[b]["df"])
                                    if "{comparison}" in template else None)
                        try:
                            v, _ = pairwise_verdict(*judge, q, doc, schema, cand[a], cand[b],
                                                    template=template, comparison=cmp_text)
                            wins[a if v == "A" else b] += 1
                        except Exception:
                            n_failed += 1
            pick = max(range(len(clusters)), key=lambda k: (wins[k], clusters[k]["votes"]))
            reason = f"round-robin wins={wins} failed={n_failed}/{n_calls}"
        else:
            cand_txt = "\n\n".join(
                f"--- Candidate {i + 1} (votes: {cl['votes']}) ---\nSQL:\n{cl['sql']}\n"
                f"Execution result:\n{result_preview(cl['df'])}"
                for i, cl in enumerate(clusters))
            prompt = JUDGE_PROMPT.format(question=q["question"], doc_section=doc,
                                         schema_section=schema, candidates=cand_txt)
            try:
                data = ask_json(*judge, prompt, 0.2)
                pick = int(data.get("winner", 0)) - 1
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
                         "judge_score": judge_score, "judge_reason": reason,
                         "probe_sql": probe_sql})
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
