"""Cross-lane answer selection over an existing pass@k run (offline, $0 Modal).

The pass@k "union" (66.7%) is the oracle ceiling: a question counts if ANY lane
solved it. The real reportable score is ONE submission per question. This script
converts the k independent lanes into a single answer per question by
self-consistency (majority vote over the submitted *result value*, not the SQL),
then reports the selected single-submission accuracy against:

  - per-lane mean (what one greedy/temp lane scores on its own), and
  - the any-of-k union ceiling.

No re-execution and no model calls: each lane's submitted result is recovered
from its trace (the submitted query_id's preview), lanes are clustered by that
value signature, and the plurality cluster's representative lane is "selected" --
so the selected answer's correctness is exactly that lane's existing score. The
clustering only decides which lane to pick; it never invents a score.

    uv run python scripts/analysis/select_passk.py                 # committed bigquery_pass8
    uv run python scripts/analysis/select_passk.py --base DIR --glob 'pass8_k*'
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO.parent


def _norm_sql(s: str) -> str:
    # all.csv stores SQL with literal "\n"/"\t" escapes; the trace has real
    # whitespace. Collapse both to single spaces so a fallback pick (which has no
    # submit_result tool call) can still be matched to its run_sql_query step.
    return " ".join((s or "").replace("\\n", " ").replace("\\t", " ").split())


def _sig(text: str) -> str:
    # Canonicalize the result preview so two lanes with the SAME answer in a
    # different row order (no ORDER BY) or spacing cluster together: keep the
    # header line, sort the data rows, lowercase. Over-splitting a correct
    # cluster would only make majority vote look worse than it is.
    lines = [l.strip().lower() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "EMPTY"
    canon = "\n".join([lines[0]] + sorted(lines[1:]))
    return hashlib.sha1(canon.encode("utf-8", "replace")).hexdigest()


def lane_answers(lane_dir: Path):
    """instance_id -> dict(score, sig, sql, preview) for one lane."""
    out = {}
    all_csv = lane_dir / "all.csv"
    if not all_csv.exists():
        return out
    rows = {r["instance_id"]: r for r in csv.DictReader(open(all_csv, encoding="utf-8"))}
    for iid, r in rows.items():
        score = 1 if r.get("score") == "1" else 0
        tp = lane_dir / "traces" / f"{iid}.json"
        preview, sql = None, (r.get("sql") or "")
        if tp.exists():
            d = json.load(open(tp, encoding="utf-8"))
            qid2prev, qid2sql, sub_qid = {}, {}, None
            for m in d.get("trace", []):
                if m.get("tool") == "run_sql_query":
                    res = m.get("result", "") or ""
                    mm = re.match(r"query_id='(q\d+)'\n?(.*)", res, re.DOTALL)
                    if mm:
                        qid2prev[mm.group(1)] = mm.group(2)
                        qid2sql[_norm_sql(m.get("args", {}).get("sql"))] = mm.group(1)
                a = m.get("assistant")
                if a and a.get("tool_calls"):
                    for tc in a["tool_calls"]:
                        if tc["function"]["name"] == "submit_result":
                            try:
                                sub_qid = json.loads(
                                    tc["function"]["arguments"]).get("query_id")
                            except Exception:
                                pass
            if sub_qid and sub_qid in qid2prev:          # normal submit
                preview = qid2prev[sub_qid]
            else:                                        # fallback: match by SQL
                qid = qid2sql.get(_norm_sql(r.get("sql")))
                if qid:
                    preview = qid2prev[qid]
        sig = _sig(preview) if preview is not None else "sql:" + _sig(_norm_sql(sql))
        out[iid] = {"score": score, "sig": sig, "sql": sql,
                    "preview": (preview or "")[:1500]}
    return out


JUDGE_PROMPT = """You are selecting the single best answer to a data question from several \
candidate SQL queries and their result previews. Judge which candidate most correctly and \
completely answers the question (right columns, grain, filters, and plausible values).

Question:
{question}
{doc_section}
Candidates:
{candidates}

Reply with ONLY a JSON object: {{"best": <candidate number>}}."""


def _plurality(records):
    """records: list of dict(score, sig, sql, preview). Return (picked_index, groups)."""
    groups = defaultdict(list)                     # sig -> [index,...]
    for idx, r in enumerate(records):
        groups[r["sig"]].append(idx)
    best_sig = max(groups, key=lambda g: (len(groups[g]),
                                          not g.startswith("sql:"), g))
    # representative = the member whose lane appears first (stable)
    return groups[best_sig][0], groups


def judge_pick(client, model, question, records, doc_text):
    """Ask the judge model to choose among the DISTINCT-result candidates."""
    seen, cands, idx_map = set(), [], []
    for idx, r in enumerate(records):
        if r["sig"] in seen:
            continue
        seen.add(r["sig"])
        n = len(cands) + 1
        idx_map.append(idx)
        cands.append(f"[{n}] SQL:\n{r['sql'][:900]}\nResult preview:\n{r['preview'][:700]}")
    if len(cands) == 1:
        return idx_map[0]
    doc_section = (f"\nAttached documentation:\n{doc_text[:6000]}\n" if doc_text else "")
    prompt = JUDGE_PROMPT.format(question=question, doc_section=doc_section,
                                 candidates="\n\n".join(cands))
    try:
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=2000,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        text = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", text, re.DOTALL)
        pick = int(json.loads(m.group(0))["best"])
        if 1 <= pick <= len(idx_map):
            return idx_map[pick - 1]
    except Exception as e:
        print(f"  [judge error, falling back to plurality: {e}]")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=str(ROOT / "bigquery_pass8"),
                    help="directory holding the lane subdirs")
    ap.add_argument("--glob", default="pass8_k*", help="lane subdir glob")
    ap.add_argument("--judge", action="store_true",
                    help="LLM-judge tie-break (needs --endpoint); else majority vote only")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--model", default="Qwen/Qwen3.6-35B-A3B")
    args = ap.parse_args()

    lanes = sorted(p for p in glob.glob(str(Path(args.base) / args.glob))
                   if (Path(p) / "all.csv").exists())
    if not lanes:
        raise SystemExit(f"no lanes under {args.base}/{args.glob}")
    print(f"lanes: {len(lanes)}  ({', '.join(os.path.basename(l) for l in lanes)})")

    per_lane = [lane_answers(Path(l)) for l in lanes]
    insts = sorted({i for la in per_lane for i in la})
    n = len(insts)
    lane_scores = [sum(r["score"] for r in la.values()) for la in per_lane]
    union = sum(1 for i in insts if any(la.get(i, {}).get("score") for la in per_lane))

    client = None
    qmap = {}
    if args.judge:
        if not args.endpoint:
            raise SystemExit("--judge needs --endpoint")
        from openai import OpenAI
        jl = ROOT / "Spider2" / "spider2-lite" / "spider2-lite.jsonl"
        for line in open(jl, encoding="utf-8"):
            d = json.loads(line)
            qmap[d["instance_id"]] = d["question"]
        key = os.environ.get("VLLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if not key:                       # fall back to ~/.nl2sql/vllm.env
            envf = Path.home() / ".nl2sql" / "vllm.env"
            if envf.exists():
                for line in envf.read_text().splitlines():
                    if line.startswith("VLLM_API_KEY="):
                        key = line.split("=", 1)[1].strip()
        client = OpenAI(base_url=args.endpoint, api_key=key or "none", timeout=300.0)

    mv_ok = judge_ok = 0
    recoverable = recovered = 0
    for i in insts:
        recs = [la[i] for la in per_lane if i in la]
        any_ok = any(r["score"] for r in recs)
        recoverable += any_ok
        pick_idx, groups = _plurality(recs)
        mv_ok += recs[pick_idx]["score"]
        if any_ok and recs[pick_idx]["score"]:
            recovered += 1
        if client is not None:
            # only invoke the judge when no strict majority lane exists
            top = max(len(v) for v in groups.values())
            if top > len(lanes) // 2:
                jidx = pick_idx
            else:
                jidx = judge_pick(client, args.model, qmap.get(i, i), recs, None)
                jidx = jidx if jidx is not None else pick_idx
            judge_ok += recs[jidx]["score"]

    mean = 100 * sum(lane_scores) / (len(lanes) * n)
    print(f"\ninstances: {n}")
    print(f"per-lane accuracy: {', '.join(f'{100*s/n:.1f}%' for s in lane_scores)}")
    print(f"per-lane mean:     {mean:.1f}%   best lane: {100*max(lane_scores)/n:.1f}%")
    print(f"union (any-of-{len(lanes)}): {union}/{n} = {100*union/n:.1f}%   (oracle ceiling)")
    print(f"\nMAJORITY-VOTE selected: {mv_ok}/{n} = {100*mv_ok/n:.1f}%  "
          f"(lift {100*mv_ok/n - mean:+.1f} pts; recovers {recovered}/{recoverable})")
    if client is not None:
        print(f"LLM-JUDGE selected:     {judge_ok}/{n} = {100*judge_ok/n:.1f}%  "
              f"(lift {100*judge_ok/n - mean:+.1f} pts)")


if __name__ == "__main__":
    main()
