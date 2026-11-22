#!/usr/bin/env python3
"""Score the pass@4 pairwise renderings with a base model or a tuned adapter.

Reports three things, because they answer different questions:
  * pairwise accuracy on the DECISIVE pairs -- directly comparable to the
    synthetic holdout number the adapter was selected on;
  * end-to-end picks per question, aggregated from the pairwise scores;
  * the pick accuracy split by question class, since all-correct questions are
    free (any pick wins) and none-correct are unwinnable (any pick loses), so
    all real signal lives in the mixed ones.

Usage:
    python scripts/score_pass4_judge.py --data pass4_armB.jsonl \
        --base Qwen/Qwen3.5-9B [--adapter runs/9b_armB_500/adapter] --out r.json
"""

import argparse
import collections
import json

import torch


def load(base, adapter, max_mem_4bit=True):
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                            bnb_4bit_compute_dtype=torch.bfloat16,
                            bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        base, quantization_config=qc if max_mem_4bit else None,
        dtype=torch.bfloat16, device_map="auto")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
        print(f"[score] adapter: {adapter}")
    model.eval()
    return model, tok


@torch.no_grad()
def score_rows(model, tok, rows, max_len, batch):
    """P(A) over {A,B} at the final position, for each rendering."""
    ids = {L: tok.encode(L, add_special_tokens=False)[0] for L in ("A", "B")}
    assert len({ids["A"], ids["B"]}) == 2
    out, trunc = [], 0
    for s in range(0, len(rows), batch):
        chunk = rows[s:s + batch]
        encs = []
        for r in chunk:
            e = tok(r["prompt"], add_special_tokens=True,
                    truncation=True, max_length=max_len - 1)["input_ids"]
            if len(e) >= max_len - 1:
                trunc += 1
            encs.append(e)
        n = max(len(e) for e in encs)
        pad = tok.pad_token_id
        inp = torch.tensor([[pad] * (n - len(e)) + e for e in encs])
        att = torch.tensor([[0] * (n - len(e)) + [1] * len(e) for e in encs])
        lg = model(input_ids=inp.to(model.device),
                   attention_mask=att.to(model.device)).logits[:, -1, :].float()
        pair = torch.stack([lg[:, ids["A"]], lg[:, ids["B"]]], dim=-1)
        pa = torch.softmax(pair, dim=-1)[:, 0].cpu().tolist()
        out.extend(pa)
        if s % (batch * 20) == 0:
            print(f"  scored {s + len(chunk)}/{len(rows)}", flush=True)
    if trunc:
        print(f"[score] WARNING {trunc}/{len(rows)} renderings hit max_len={max_len}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data)]
    model, tok = load(args.base, args.adapter)
    pa = score_rows(model, tok, rows, args.max_len, args.batch)

    # order-symmetric score per unordered pair: s(i,j) = mean over the two
    # renderings of "probability that i is the better candidate"
    sym = collections.defaultdict(list)
    for r, p in zip(rows, pa):
        key = (r["instance_id"], r["i"], r["j"])
        # p is P(first slot). Convert to P(i beats j).
        sym[key].append(p if r["first"] == r["i"] else 1.0 - p)
    s_ij = {k: sum(v) / len(v) for k, v in sym.items()}

    # pairwise accuracy on decisive pairs
    meta = {(r["instance_id"], r["i"], r["j"]): r for r in rows}
    dec_ok = dec_n = 0
    for k, s in s_ij.items():
        m = meta[k]
        if not m["decisive"]:
            continue
        dec_n += 1
        pick_i = s > 0.5
        if pick_i == bool(m["i_correct"]):
            dec_ok += 1

    # aggregate into a per-question pick
    byq = collections.defaultdict(dict)
    corr = {}
    for k, s in s_ij.items():
        iid, i, j = k
        m = meta[k]
        byq[iid][i] = byq[iid].get(i, 0.0) + s
        byq[iid][j] = byq[iid].get(j, 0.0) + (1.0 - s)
        corr.setdefault(iid, {})[i] = bool(m["i_correct"])
        corr[iid][j] = bool(m["j_correct"])

    tot = collections.Counter()
    ok = collections.Counter()
    for iid, scores in byq.items():
        cs = corr[iid]
        cls = "all" if all(cs.values()) else ("none" if not any(cs.values()) else "mixed")
        tot[cls] += 1
        pick = max(scores, key=lambda c: scores[c])
        if cs[pick]:
            ok[cls] += 1

    total = sum(ok.values())
    n_all, n_mix, n_non = tot["all"], tot["mixed"], tot["none"]
    ach = n_all + n_mix
    print("\n==== RESULT " + (args.adapter or "UNTUNED BASE") + " ====")
    print(f"decisive pairwise   {dec_ok}/{dec_n} = {dec_ok/max(dec_n,1):.4f}")
    print(f"picks total         {total}/{sum(tot.values())}")
    print(f"  all-correct       {ok['all']}/{n_all}")
    print(f"  MIXED (signal)    {ok['mixed']}/{n_mix} = {ok['mixed']/max(n_mix,1):.4f}")
    print(f"  none-correct      {ok['none']}/{n_non}")
    print(f"on {ach} achievable  {ok['all']+ok['mixed']}/{ach} = "
          f"{(ok['all']+ok['mixed'])/max(ach,1):.4f}")
    if args.out:
        json.dump({"adapter": args.adapter, "data": args.data,
                   "decisive_pairwise": dec_ok / max(dec_n, 1),
                   "decisive_n": dec_n, "total": total,
                   "mixed_ok": ok["mixed"], "mixed_n": n_mix,
                   "all_ok": ok["all"], "all_n": n_all,
                   "none_ok": ok["none"], "none_n": n_non},
                  open(args.out, "w"), indent=2)
        print(f"-> {args.out}")


if __name__ == "__main__":
    main()
