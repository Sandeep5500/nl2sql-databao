#!/usr/bin/env python3
"""Log-likelihood of stored judge reasoning under a served model, for the V-STaR-style check in
documents/head_probe_prereg.md (step 2): does a DPO-trained judge (v2a, v3c; DPO from the base, so
the base is its reference) already rank right traces above wrong ones? The implicit reward of a trace
is log pi_dpo(y|x) - log pi_base(y|x), y = reasoning + '\\n</think>\\n\\n' + the stored reply.

Scores only held-out practice traces (questions on --holdout databases or in the val split, recorded as split "heldout"), so
no model saw them in training. One request per trace to a vLLM server: /v1/completions with the
token ids, max_tokens=1 and prompt_logprobs=0 (the logprob of each prompt token); the reply's tokens
are summed. Appends to --out and skips traces already there.

    python scripts/vstar_scores.py --endpoint http://localhost:8765/v1 --model base \\
        --verdicts <files> --holdout holdout.json --out scores_base.jsonl
"""

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "Qwen/Qwen3.6-35B-A3B"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True, help="served model name")
    ap.add_argument("--verdicts", nargs="+", required=True)
    ap.add_argument("--holdout", required=True, help="make_judge_sft_dpo.py holdout.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tokenizer", default=BASE)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    held = set(json.load(open(args.holdout))["databases"])
    rows = []
    for path in args.verdicts:
        tag = Path(path).stem.removeprefix("verdicts_")
        for line in open(path):
            r = json.loads(line)
            if not (r["split"] == "heldout" or r["db"] in held):  # the val split is recorded as "heldout"
                continue
            for pi, p in enumerate(r["pairs"]):
                for si, s in enumerate(p["samples"]):
                    if s.get("error") or s.get("truncated") or s.get("verdict") not in ("A", "B") \
                            or not (s.get("reasoning") or "").strip() or not s.get("answer"):
                        continue
                    rows.append(dict(id=f"{tag}|{r['instance_id']}|{pi}|{si}", file=tag, instance_id=r["instance_id"],
                                     db=r["db"], split=r["split"], source=r["source"], pair=pi, first=p["first"],
                                     second=p["second"], sample=si, correct_letter=p["correct_letter"],
                                     verdict=s["verdict"], right=s["verdict"] == p["correct_letter"],
                                     prompt=p["prompt"], reasoning=s["reasoning"], answer=s["answer"]))
    out = Path(args.out)
    done = {json.loads(l)["id"] for l in open(out)} if out.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    print(f"{len(rows)} held-out traces; {len(todo)} to score with {args.model}", flush=True)

    def score(r):
        gen = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}], tokenize=False,
                                      add_generation_prompt=True, enable_thinking=True)
        gen_ids = tok(gen, add_special_tokens=False).input_ids
        ids = tok(gen + r["reasoning"].strip() + "\n</think>\n\n" + r["answer"], add_special_tokens=False).input_ids
        if ids[:len(gen_ids)] != gen_ids:
            raise SystemExit("the generation prompt does not tokenize as a prefix")
        body = json.dumps({"model": args.model, "prompt": ids, "max_tokens": 1, "temperature": 0,
                           "prompt_logprobs": 0}).encode()
        req = urllib.request.Request(args.endpoint.rstrip("/") + "/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=600))
        except Exception as e:  # skipped now, scored by a rerun
            print(f"{r['id']}: {str(e)[:120]}", flush=True)
            return None
        plp = resp["choices"][0]["prompt_logprobs"]
        lp = 0.0
        for i in range(len(gen_ids), len(ids)):
            d = plp[i]
            lp += float(d[str(ids[i])]["logprob"])
        meta = {k: v for k, v in r.items() if k not in ("prompt", "reasoning", "answer")}
        return dict(meta, model=args.model, logp=lp, n_tokens=len(ids) - len(gen_ids))

    failed = 0
    with ThreadPoolExecutor(args.workers) as ex, open(out, "a") as f:
        for n, rec in enumerate(ex.map(score, todo), 1):
            if rec is None:
                failed += 1
                continue
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if n % 100 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print(f"done; {failed} failed", flush=True)


if __name__ == "__main__":
    main()
