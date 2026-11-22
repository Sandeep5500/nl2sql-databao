#!/usr/bin/env python3
"""QLoRA pairwise SFT for the judge: one prompt, one target token.

The objective is ordinary causal-LM loss **masked to a single position** -- the
"A"/"B" token that follows the prompt. On a two-way choice that loss *is* the
binary cross-entropy we want, so no classification head is needed; adding one
would break vLLM serving and buy nothing.

Not DPO. The preference is one token against another with near-identical
embeddings, which is exactly the regime where likelihood displacement bites
(Razin et al.): DPO can satisfy its objective by pushing the rejected token down
while probability mass drifts to a third output, and the damage surfaces as
unparseable verdicts that read like a prompt bug. SFT also yields the calibrated
margin that Copeland tie-breaking needs.

Confidence is never generated. At eval and at serving it is read off the logits:

    P(A > B) = softmax([logprob("A"), logprob("B")])[0]

and scored order-symmetrically over the two renderings of each pair, which makes
an order flip structurally impossible rather than something training must wash
out. Our judge flips on 44% of decisive pairs today.

Usage (on a GPU node, from nl2sql-v2/):
    uv run python scripts/train_judge_sft.py \\
        --data ~/judge/armA.jsonl --out ~/judge/runs/armA_935 \\
        --limit-pairs 935 --epochs 3
    # baseline only, no training:
    uv run python scripts/train_judge_sft.py --data ~/judge/armA.jsonl --eval-only
"""

import argparse
import collections
import json
import math
import os
import random
from pathlib import Path

import torch


def load(path, split):
    out = []
    for line in open(path):
        r = json.loads(line)
        if r["split"] == split:
            out.append(r)
    return out


def limit_by_pairs(rows, n_pairs, seed=13):
    """Nested subsets for the scaling curve, chosen at PAIR granularity so both
    renderings of a pair stay together -- otherwise a rung trains on one
    ordering of a pair and is evaluated having seen the other."""
    if not n_pairs:
        return rows
    pids = sorted({r["pair_id"] for r in rows})
    random.Random(seed).shuffle(pids)
    keep = set(pids[:n_pairs])
    return [r for r in rows if r["pair_id"] in keep]


class PairDS(torch.utils.data.Dataset):
    def __init__(self, rows, tok, max_len):
        self.rows, self.tok, self.max_len = rows, tok, max_len
        # single-token ids for the two answers; assert they really are one token
        self.ids = {}
        for letter in ("A", "B"):
            enc = tok.encode(letter, add_special_tokens=False)
            assert len(enc) == 1, f"{letter!r} is not one token: {enc}"
            self.ids[letter] = enc[0]

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        p = self.tok(r["prompt"], add_special_tokens=True,
                     truncation=True, max_length=self.max_len - 1)["input_ids"]
        tgt = self.ids[r["target"]]
        ids = p + [tgt]
        # loss on the final position only
        labels = [-100] * len(p) + [tgt]
        return {"input_ids": ids, "labels": labels}


def collate(batch, pad_id):
    n = max(len(b["input_ids"]) for b in batch)
    out = {"input_ids": [], "labels": [], "attention_mask": []}
    for b in batch:
        k = n - len(b["input_ids"])
        out["input_ids"].append(b["input_ids"] + [pad_id] * k)
        out["labels"].append(b["labels"] + [-100] * k)
        out["attention_mask"].append([1] * len(b["input_ids"]) + [0] * k)
    return {k: torch.tensor(v) for k, v in out.items()}


@torch.no_grad()
def evaluate(model, tok, rows, ids, max_len, batch=4):
    """Two numbers: per-rendering accuracy, and order-symmetric per-pair accuracy."""
    model.eval()
    per_render, by_pair = [], collections.defaultdict(dict)
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        enc = tok([r["prompt"] for r in chunk], return_tensors="pt", padding=True,
                  truncation=True, max_length=max_len - 1, add_special_tokens=True)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        logits = model(**enc).logits
        last = enc["attention_mask"].sum(1) - 1
        for j, r in enumerate(chunk):
            lg = logits[j, last[j]].float()
            la, lb = lg[ids["A"]].item(), lg[ids["B"]].item()
            p_a = 1.0 / (1.0 + math.exp(-(la - lb)))          # softmax over the two
            pred = "A" if p_a >= 0.5 else "B"
            per_render.append(pred == r["target"])
            # which side held `chosen` in this rendering
            side = "chosen_first" if r["target"] == "A" else "rejected_first"
            by_pair[r["pair_id"]][side] = p_a
            by_pair[r["pair_id"]]["meta"] = r

    sym_ok, sym_n = 0, 0
    for pid, d in by_pair.items():
        if "chosen_first" not in d or "rejected_first" not in d:
            continue
        # s = P(chosen wins) averaged over both orderings
        s = 0.5 * (d["chosen_first"] + (1.0 - d["rejected_first"]))
        sym_ok += s > 0.5
        sym_n += 1
    return (sum(per_render) / max(len(per_render), 1),
            sym_ok / max(sym_n, 1), sym_n, by_pair)


def breakdown(by_pair):
    """Where the judge fails -- the slice that decides whether arm A is viable."""
    cells = collections.defaultdict(lambda: [0, 0])
    for pid, d in by_pair.items():
        if "chosen_first" not in d or "rejected_first" not in d:
            continue
        m = d["meta"]
        s = 0.5 * (d["chosen_first"] + (1.0 - d["rejected_first"]))
        for key in (f"error={m['error_type']}",
                    "gold=1row" if m["gold_rows"] == 1 else "gold=multirow",
                    "hard" if m["hard"] else "normal"):
            cells[key][0] += 1
            cells[key][1] += s > 0.5
    return cells


def training_args(out, args):
    """TrainingArguments, minus whatever this transformers version dropped.

    transformers 5.x removed some long-standing names (warmup_ratio among
    them). Filtering against the real signature keeps one script working
    across the serving env (5.5.3) and the training env (5.22.1) instead of
    failing after the model is already loaded.
    """
    import inspect
    from transformers import TrainingArguments
    want = dict(
        output_dir=str(out), num_train_epochs=args.epochs,
        per_device_train_batch_size=1, gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.03,
        logging_steps=5, bf16=True,
        # a rung is only 93-348 optimizer steps at grad_accum=16, so save
        # often: save_steps=200 never fired for the 250- and 500-pair rungs.
        save_strategy="steps", save_steps=20, save_total_limit=1,
        gradient_checkpointing=True, report_to=[], seed=args.seed,
        optim="paged_adamw_8bit")
    ok = set(inspect.signature(TrainingArguments.__init__).parameters)
    dropped = sorted(k for k in want if k not in ok)
    if dropped:
        print(f"[train] TrainingArguments has no {dropped}; omitted")
        want = {k: v for k, v in want.items() if k in ok}
    return TrainingArguments(**want)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="armA/armB/armC jsonl")
    ap.add_argument("--base", default="Qwen/Qwen3.6-35B-A3B")
    ap.add_argument("--out")
    ap.add_argument("--limit-pairs", type=int, default=0, help="scaling-curve rung")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--eval-batch", type=int, default=4)
    ap.add_argument("--eval-only", action="store_true",
                    help="untuned baseline -- the curve has no origin without it")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig, Trainer, TrainingArguments)

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"

    train = limit_by_pairs(load(args.data, "train"), args.limit_pairs, args.seed)
    held = load(args.data, "holdout")
    print(f"{Path(args.data).name}: {len(train)} train examples "
          f"({len({r['pair_id'] for r in train})} pairs) | "
          f"{len(held)} holdout examples ({len({r['pair_id'] for r in held})} pairs)")

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                              bnb_4bit_compute_dtype=torch.bfloat16,
                              bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=quant, torch_dtype=torch.bfloat16,
        device_map="auto", attn_implementation="sdpa")
    model.config.use_cache = False

    ds = PairDS(train, tok, args.max_len)
    ids = ds.ids

    print("\n--- baseline (untuned) on held-out ---")
    acc, sym, n, bp = evaluate(model, tok, held, ids, args.max_len, args.eval_batch)
    print(f"per-rendering {acc:.4f} | order-symmetric per-pair {sym:.4f} over {n} pairs")
    print("  reference: 'always A' = 0.5000 exactly (position-balanced)")
    for k, (t, ok) in sorted(breakdown(bp).items()):
        print(f"  {k:22s} {ok}/{t} = {ok/t:.3f}")
    if args.eval_only:
        return

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    model = prepare_model_for_kbit_training(model,
                                           use_gradient_checkpointing=True)
    # attention projections only. MoE expert-wise LoRA is fiddly and rarely
    # needed when the task is discrimination over evidence already in the prompt.
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()

    out = Path(args.out or f"./runs/{Path(args.data).stem}_{args.limit_pairs or 'all'}")
    trainer = Trainer(
        model=model, train_dataset=ds,
        data_collator=lambda b: collate(b, tok.pad_token_id),
        args=training_args(out, args),
    )
    # the preempt partition requeues on preemption, which restarts the script
    # from the top; without this a 90-minute rung can lose all of it repeatedly.
    ckpts = sorted(out.glob("checkpoint-*"),
                   key=lambda d: int(d.name.split("-")[1])) if out.exists() else []
    if ckpts:
        print(f"[train] resuming from {ckpts[-1].name}")
    trainer.train(resume_from_checkpoint=str(ckpts[-1]) if ckpts else None)

    print("\n--- tuned on held-out ---")
    acc2, sym2, n2, bp2 = evaluate(model, tok, held, ids, args.max_len, args.eval_batch)
    print(f"per-rendering {acc2:.4f} ({acc2-acc:+.4f}) | "
          f"order-symmetric {sym2:.4f} ({sym2-sym:+.4f}) over {n2} pairs")
    for k, (t, ok) in sorted(breakdown(bp2).items()):
        print(f"  {k:22s} {ok}/{t} = {ok/t:.3f}")

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out / "adapter"))
    json.dump({"data": args.data, "pairs": args.limit_pairs or "all",
               "epochs": args.epochs, "lr": args.lr, "rank": args.rank,
               "baseline_per_rendering": acc, "baseline_symmetric": sym,
               "tuned_per_rendering": acc2, "tuned_symmetric": sym2,
               "holdout_pairs": n2},
              open(out / "result.json", "w"), indent=2)
    print(f"\nadapter + result.json -> {out}")


if __name__ == "__main__":
    main()
