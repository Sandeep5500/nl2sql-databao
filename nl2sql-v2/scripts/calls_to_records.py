#!/usr/bin/env python3
"""The stored selection-eval judge calls (rejudge_pools.py calls_<variant>.jsonl) as
sample_judge_verdicts.py records, so extract_judge_states.py reads them unchanged: Stage B step 3 of
documents/head_probe_prereg.md (hidden states of the diff_cmp calls, for the frozen probe).

One record per pool (instance_id = the pool key, split = its half, db = its database or "bq"), one pair
per ordered pair of groups, and as samples the stored calls in sample order (the reasoning; the answer
rebuilt from the verdict, the only part of it extraction reads). Prompts are rebuilt as
rejudge_pools.py built them: its Contexts, the reference pools and the build_compare_cache.py texts.
correct_letter is None when both groups are right or both wrong. Nothing is fit here. Prereg
engineering check: every prompt has a non-empty schema section, and a doc section wherever the question
has one; the run stops otherwise.

Usage (on Babel, NL2SQL_DATA_ROOT set; from nl2sql-v2/):
    python scripts/calls_to_records.py --calls calls_diff_cmp.jsonl --evalset selection_evalset.json \\
        --pools $W/results/pools --bq-pools $B/pools --bq-base $B/bigquery_passk_nov2026 \\
        --bq-questions $B/bq_questions.jsonl --comparisons compare_cache.jsonl --select half=design \\
        --out verdicts_design.jsonl
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", required=True)
    ap.add_argument("--variant", default="diff_cmp")
    ap.add_argument("--evalset", required=True)
    ap.add_argument("--select", default="", help="eval set filters, e.g. half=design or half=test|bq")
    ap.add_argument("--pools", required=True, help="Spider2 results/pools dir (reference pools)")
    ap.add_argument("--ref-prefix", default="think35/qwen36-35b-think")
    ap.add_argument("--bq-pools", default="")
    ap.add_argument("--bq-ref-prefix", default="think35_bq")
    ap.add_argument("--bq-base")
    ap.add_argument("--bq-questions")
    ap.add_argument("--comparisons", help="build_compare_cache.py output, for variants with {comparison}")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from judge_prompts import VARIANTS
    from rejudge_pools import Contexts, load_reference
    from selection_eval import signature

    spec = VARIANTS[args.variant]
    ev = json.loads(Path(args.evalset).read_text())["pools"]
    filt = [f.split("=") for f in args.select.split(";") if f]
    calls = defaultdict(list)
    for c in map(json.loads, open(args.calls)):
        e = ev.get(c["key"])
        if e and all(str(e[name]) in want.split("|") for name, want in filt):
            calls[(c["key"], c["first"], c["second"])].append(c)
    keys = sorted({k for k, _, _ in calls})
    ref = load_reference(args.pools, args.ref_prefix, args.bq_pools, args.bq_ref_prefix)
    for k in keys:
        if json.dumps(signature(ref[k])) != json.dumps(ev[k]["sig"]):
            raise SystemExit(f"{k}: reference pool differs from the eval set")
    comps = {}
    if "{comparison}" in spec["template"]:
        for r in map(json.loads, open(args.comparisons)):
            comps[(r["key"], r["first"], r["second"])] = r["text"]
    by_key = defaultdict(list)
    for k, a, b in sorted(calls):
        by_key[k].append((a, b))

    ctx = Contexts(args)
    n_docs = n_pairs = n_calls = n_unavail = 0
    with open(args.out, "w") as out:
        for k in keys:
            it, e = ref[k], ev[k]
            question, doc, schema = ctx.get(k, it)
            q = (ctx.bqmeta if k.startswith("bq:") else ctx.qmeta)[it["instance_id"]]
            if not schema.strip():
                raise SystemExit(f"{k}: empty schema section")
            if q.get("doc") if k.startswith("bq:") else q.get("external_knowledge"):
                if not doc.strip():
                    raise SystemExit(f"{k}: the question has a doc but the prompt has none")
                n_docs += 1
            pairs = []
            for a, b in by_key[k]:
                ga, gb = it["groups"][a], it["groups"][b]
                fields = dict(question=question, doc_section=doc, schema_section=schema,
                              sql_a=ga["sql"], res_a=ga["preview"], sql_b=gb["sql"], res_b=gb["preview"])
                if "{comparison}" in spec["template"]:
                    fields["comparison"] = comps.get((k, a, b), "Comparison unavailable.")
                    n_unavail += fields["comparison"] == "Comparison unavailable."
                ca, cb = e["groups"][a][1], e["groups"][b][1]
                samples = [dict(verdict=c["verdict"], reasoning=c.get("reasoning") or "",
                                answer=json.dumps({"winner": c["verdict"], "reason": c.get("reason") or ""})
                                if c["verdict"] else "", truncated=bool(c.get("truncated")),
                                error=c.get("error") or "", p_first=c.get("p_first"), call_sample=c["sample"])
                           for c in sorted(calls[(k, a, b)], key=lambda c: c["sample"])]
                pairs.append(dict(first=a, second=b, correct_letter=None if ca == cb else ("A" if ca else "B"),
                                  prompt=spec["template"].format(**fields), samples=samples))
                n_pairs += 1
                n_calls += len(samples)
            out.write(json.dumps(dict(instance_id=k, db=e.get("db") or "bq", split=e["half"], source=e["bench"],
                                      stratum=e["stratum"], pairs=pairs)) + "\n")
    print(f"{len(keys)} pools ({n_docs} with a doc section, every schema section non-empty), {n_pairs} ordered "
          f"pairs ({n_unavail} without a comparison), {n_calls} calls -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
