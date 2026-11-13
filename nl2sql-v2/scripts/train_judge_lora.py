#!/usr/bin/env python3
"""LoRA SFT, then DPO, for the pairwise judge, on the files make_judge_sft_dpo.py writes.

The base is the bf16 release of the deployed model (Qwen/Qwen3.6-35B-A3B; the server runs
QuantTrio's AWQ build of it, which quantizes only the routed experts). The adapter goes on
modules that build keeps in bf16, so vLLM can serve it there with --enable-lora: full
attention (q/k/v/o), linear attention (its input and output projections) and the shared
expert MLP. Routed experts, the router and the vision tower stay frozen and untouched.

  sft  {"messages": [user, assistant]} rows; loss on the assistant turn only, which
       carries the reasoning as reasoning_content (rendered as the <think> block)
  dpo  {"prompt", "chosen", "rejected"} rows. With --init, the SFT adapter is merged into
       the base in memory and a new adapter trained on top, so the frozen reference (the new
       adapter switched off) is the SFT policy. At the end the two adapters are joined into
       one (stacked along the rank, each side's scale folded in), which computes exactly
       SFT + DPO, so a single adapter serves on the AWQ build. Without --init, DPO starts
       from the base, which is then the reference, and the adapter is the DPO one alone
  choice  {"prompt", "correct_letter"} rows (make_judge_sft_dpo.py's choice.jsonl): the verdict
       alone, no reasoning. The prompt is rendered with thinking off and followed by the
       reply's opening '{\\n "winner": "' (what the untuned judge writes with thinking off);
       the loss is cross-entropy over the two letter tokens at the next position, so the
       only thing trained is P(correct letter), the quantity judge_pools.py reads at
       inference (thinking off, winner_prob)
  choice_mt  choice rows as above, plus sft.jsonl rows (--sft-data: the judge's own right reasoning,
       thinking on) with a next-token loss weighted --weight: two losses on one adapter, the pick
       still made with thinking off (as GenRM / distilling step-by-step train a rationale alongside)
  choice_reason  dpo.jsonl rows: the letter is read after the judge's own reasoning (thinking on,
       '<think>' + reasoning + '</think>' + '{"winner": "'), once after the right and once after the
       wrong sample of the same prompt, and must be the correct letter both times; plus --weight x
       the next-token loss on the right sample's reasoning. Served as a separate scorer that reads a
       base judge's reasoning (prefill only), so the reasoning itself is never changed

Checkpoints every --save-steps; a rerun with the same --out resumes from the latest, so
a preempted job just requeues. The finished adapter is written to <out>/final (for dpo,
the joined one; the DPO part alone is in <out>/dpo_only).

Usage (GPU node; the base fits on two 80GB GPUs, spread layer by layer):
    python scripts/train_judge_lora.py sft --data ../results/judge_train/data/sft.jsonl \\
        --out ../results/judge_train/sft
    python scripts/train_judge_lora.py dpo --data ../results/judge_train/data/dpo.jsonl \\
        --init ../results/judge_train/sft/final --out ../results/judge_train/dpo
    python scripts/train_judge_lora.py sft --base <tiny model dir> ... --max-steps 2
        (smoke test on a small model of the same architecture)
"""

import argparse
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

BASE = "Qwen/Qwen3.6-35B-A3B"
# modules the AWQ serving build leaves in bf16 (its modules_to_not_convert), by group
TARGETS = {
    "attention": r"self_attn\.(q_proj|k_proj|v_proj|o_proj)",
    "linear_attention": r"linear_attn\.(in_proj_qkvz|in_proj_ba|in_proj_qkv|in_proj_z|in_proj_a|in_proj_b|out_proj)",
    "shared_expert": r"shared_expert\.(gate_proj|up_proj|down_proj)",
}


def target_modules(model) -> list[str]:
    """Names of the Linear layers to adapt, found on the loaded model (transformers may
    name or fuse them differently from the checkpoint); fails if a group is missing."""
    import torch.nn as nn
    found, groups = [], Counter()
    for name, mod in model.named_modules():
        if not isinstance(mod, nn.Linear) or "visual" in name or "mtp" in name:
            continue
        for group, pat in TARGETS.items():
            if re.search(rf"layers\.\d+\.(mlp\.)?{pat}$", name):
                found.append(name)
                groups[group] += 1
    print("adapter targets:", dict(groups))
    missing = [g for g in TARGETS if not groups[g]]
    if missing:
        raise SystemExit(f"no Linear layers found for {missing}; inspect model.named_modules()")
    return found


def join_adapters(first: Path, second: Path, out: Path):
    """One LoRA adapter equal to applying both: A matrices stacked along the rank, B
    matrices side by side, each adapter's scale (alpha / r) folded into its B, and alpha
    set to the joined rank (scale 1)."""
    import torch
    from safetensors.torch import load_file, save_file
    c1, c2 = (json.loads((d / "adapter_config.json").read_text()) for d in (first, second))
    w1, w2 = (load_file(str(d / "adapter_model.safetensors")) for d in (first, second))
    if set(w1) != set(w2) or c1.get("rank_pattern") or c2.get("rank_pattern"):
        raise SystemExit("adapters do not share targets; cannot join")
    s1, s2 = c1["lora_alpha"] / c1["r"], c2["lora_alpha"] / c2["r"]
    joined = {}
    for k in w1:
        if ".lora_A." in k:
            joined[k] = torch.cat([w1[k], w2[k]], dim=0).contiguous()
        elif ".lora_B." in k:
            joined[k] = torch.cat([w1[k] * s1, w2[k] * s2], dim=1).contiguous()
        else:
            raise SystemExit(f"unexpected adapter tensor {k}")
    out.mkdir(parents=True, exist_ok=True)
    save_file(joined, str(out / "adapter_model.safetensors"))
    r = c1["r"] + c2["r"]
    (out / "adapter_config.json").write_text(json.dumps({**c1, "r": r, "lora_alpha": r}, indent=1))


def load_rows(path: str, limit: int | None, seed: int) -> list[dict]:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if limit:
        rows = random.Random(seed).sample(rows, min(limit, len(rows)))
    return rows


def check_template(tok, user: list[dict], reply: list[dict]):
    """The chat template must render the reasoning, and render the prompt as a prefix of
    the whole conversation, or the completion mask lands in the wrong place."""
    prompt = tok.apply_chat_template(user, tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(user + reply, tokenize=False)
    reasoning = reply[0].get("reasoning_content") or ""
    if not full.startswith(prompt):
        raise SystemExit("chat template: the prompt is not a prefix of the conversation\n"
                         f"prompt tail: {prompt[-200:]!r}\nfull: {full[len(prompt) - 200:len(prompt) + 200]!r}")
    if reasoning and reasoning.strip()[:80] not in full:
        raise SystemExit("chat template dropped the reasoning_content")
    print("chat template ok; completion starts:", repr(full[len(prompt):len(prompt) + 120]))


def device_map(base: str):
    """transformers' "auto" placement over the visible GPUs, with lm_head moved to the first.
    The trainers put the inputs there and combine them with the model's outputs (losses,
    masks, entropies), which come out wherever lm_head is. The first GPU therefore keeps 30GiB
    free of weights for the logits (248k vocabulary, chosen and rejected, up to 12k tokens);
    that matters on 48GB GPUs, not on 80GB ones."""
    import torch
    from accelerate import init_empty_weights
    from transformers import AutoConfig, AutoModelForImageTextToText
    from transformers.integrations.accelerate import _get_device_map
    if torch.cuda.device_count() < 2:
        return "auto"
    with init_empty_weights():
        empty = AutoModelForImageTextToText.from_config(AutoConfig.from_pretrained(base),
                                                        dtype=torch.bfloat16)
    total = [torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count())]
    budget = {i: int(t * 0.9) for i, t in enumerate(total)}
    budget[0] = max(total[0] - 30 * 2**30, 8 * 2**30)
    placed = _get_device_map(empty, "auto", budget, None)
    placed["lm_head"] = 0
    return placed


CHOICE_PREFIX = '{\n "winner": "'
REASON_PREFIX = '{"winner": "'  # the thinking judge's reply opening (10,710 of 10,715 stored answers)


def tail_logits(model, ids, k):
    """Logits of the last k positions of one sequence (ids: [1, L] on the input device)."""
    import torch
    kw = dict(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False)
    return model(**kw, logits_to_keep=k).logits[0]


def letter_ids_after(tok, text):
    ids = tok(text, add_special_tokens=False).input_ids
    out = []
    for letter in "AB":
        full = tok(text + letter, add_special_tokens=False).input_ids
        if full[:-1] != ids:
            raise SystemExit(f"letter {letter} does not tokenize as one token after the prefix")
        out.append(full[-1])
    return out


def thinking_text(tok, user, reasoning):
    """The prompt rendered with thinking on, the judge's own reasoning, and its reply opening up to
    the letter: token for token what the judge produced (extract_judge_states.py rebuilds the same)."""
    gen = tok.apply_chat_template(user, tokenize=False, add_generation_prompt=True, enable_thinking=True)
    return gen, gen + reasoning.strip() + "\n</think>\n\n" + REASON_PREFIX


def mt_rows(tok, choice, sft, max_length):
    """choice_mt rows: choice.jsonl rows as in choice_rows (kind "choice") and sft.jsonl rows (kind
    "sft": the right sample's reasoning and reply, rendered with thinking on, n_prompt = where the
    completion starts) for a next-token loss on the judge's own correct reasoning."""
    kept, letter_ids = choice_rows(tok, choice, max_length)
    for r in kept:
        r.update(kind="choice", n_prompt=0)  # every row carries the same columns
    too_long = 0
    for r in sft:
        user = r["messages"][:-1]
        prompt = tok.apply_chat_template(user, tokenize=False, add_generation_prompt=True, enable_thinking=True)
        full = tok.apply_chat_template(r["messages"], tokenize=False)
        if not full.startswith(prompt):
            raise SystemExit("sft row: the thinking-on prompt is not a prefix of the conversation")
        ids = tok(full, add_special_tokens=False).input_ids
        n_prompt = len(tok(prompt, add_special_tokens=False).input_ids)
        if len(ids) > max_length:
            too_long += 1
            continue
        kept.append({"kind": "sft", "input_ids": ids, "n_prompt": n_prompt, "label": -1})
    print(f"choice_mt: {sum(r['kind'] == 'sft' for r in kept)} sft rows kept ({too_long} too long)")
    return kept, letter_ids


def reason_rows(tok, rows, max_length):
    """choice_reason rows from dpo.jsonl: one right and one wrong reasoning sample of the same prompt,
    each rendered by thinking_text; label = the correct letter (0 = A, 1 = B)."""
    out, letter_ids, too_long = [], None, 0
    for r in rows:
        seqs = []
        for side in ("chosen", "rejected"):
            gen, text = thinking_text(tok, r["prompt"], r[side][0]["reasoning_content"])
            if letter_ids is None:
                letter_ids = letter_ids_after(tok, text)
                print("choice_reason: text ends", repr(text[-60:]), "letter ids", letter_ids)
            seqs.append((tok(text, add_special_tokens=False).input_ids, len(tok(gen, add_special_tokens=False).input_ids)))
        if max(len(s[0]) for s in seqs) > max_length:
            too_long += 1
            continue
        out.append({"right_ids": seqs[0][0], "right_n_prompt": seqs[0][1], "wrong_ids": seqs[1][0],
                    "label": "AB".index(r["correct_letter"])})
    print(f"choice_reason: {len(rows)} rows, {len(out)} within {max_length} tokens ({too_long} dropped)")
    return out, letter_ids


def nll(logits, targets):
    """Mean next-token NLL, computed in chunks in float32."""
    import torch
    tot, n = 0.0, targets.numel()
    for i in range(0, n, 1024):
        tot = tot + torch.nn.functional.cross_entropy(logits[i:i + 1024].float(), targets[i:i + 1024], reduction="sum")
    return tot / max(1, n)


def two_loss_trainer(model, cfg, ds, letter_ids, stage, weight):
    """choice_mt: 2-way letter cross-entropy on choice rows; weight x next-token loss on sft rows.
    choice_reason: letter cross-entropy after the right and after the wrong reasoning sample (the
    pick must be correct either way), plus weight x next-token loss on the right sample's reasoning."""
    import torch
    from transformers import Trainer

    class TwoLossTrainer(Trainer):
        hits, pick_l, reason_l = [], [], []

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.model_accepts_loss_kwargs = False

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            dev = inputs["input_ids"].device if "input_ids" in inputs else inputs["right_ids"].device
            label = inputs["labels"].to(dev)
            if stage == "choice_mt":
                ids = inputs["input_ids"]
                if inputs["kind"] == "choice":
                    two = tail_logits(model, ids, 1)[-1, letter_ids].float()[None]
                    loss = torch.nn.functional.cross_entropy(two, label.to(two.device))
                    TwoLossTrainer.hits.append(int(two.argmax(-1).item() == label.item()))
                    TwoLossTrainer.pick_l.append(float(loss))
                else:
                    n0 = int(inputs["n_prompt"])
                    lg = tail_logits(model, ids, ids.shape[1] - n0 + 1)[:-1]
                    loss = weight * nll(lg, ids[0, n0:].to(lg.device))
                    TwoLossTrainer.reason_l.append(float(loss) / weight)
                return loss
            # choice_reason
            r_ids, w_ids, n0 = inputs["right_ids"], inputs["wrong_ids"], int(inputs["right_n_prompt"])
            lr = tail_logits(model, r_ids, r_ids.shape[1] - n0 + 1)
            two_r = lr[-1, letter_ids].float()[None]
            two_w = tail_logits(model, w_ids, 1)[-1, letter_ids].float()[None]
            lab = label.to(two_r.device)
            pick = 0.5 * (torch.nn.functional.cross_entropy(two_r, lab)
                          + torch.nn.functional.cross_entropy(two_w.to(two_r.device), lab))
            reason = nll(lr[:-1], r_ids[0, n0:].to(lr.device))
            TwoLossTrainer.hits += [int(two_r.argmax(-1).item() == lab.item()),
                                    int(two_w.argmax(-1).item() == lab.item())]
            TwoLossTrainer.pick_l.append(float(pick))
            TwoLossTrainer.reason_l.append(float(reason))
            return pick + weight * reason

        def log(self, logs, *a, **k):
            if "loss" in logs:
                for name, vals in (("pick_acc", TwoLossTrainer.hits), ("pick_loss", TwoLossTrainer.pick_l),
                                   ("reason_nll", TwoLossTrainer.reason_l)):
                    if vals:
                        logs[name] = round(sum(vals) / len(vals), 4)
                TwoLossTrainer.hits, TwoLossTrainer.pick_l, TwoLossTrainer.reason_l = [], [], []
            super().log(logs, *a, **k)

    def collate(batch):
        if len(batch) != 1:
            raise SystemExit(f"{stage} runs with --batch 1 (rows are not padded)")
        b = batch[0]
        if stage == "choice_mt":
            return {"input_ids": torch.tensor([b["input_ids"]]), "labels": torch.tensor([b["label"]]),
                    "kind": b["kind"], "n_prompt": b.get("n_prompt", 0)}
        return {"right_ids": torch.tensor([b["right_ids"]]), "wrong_ids": torch.tensor([b["wrong_ids"]]),
                "right_n_prompt": b["right_n_prompt"], "labels": torch.tensor([b["label"]])}

    return TwoLossTrainer(model=model, args=cfg, train_dataset=ds, data_collator=collate)


def choice_rows(tok, rows, max_length):
    """Token ids of each prompt (thinking off, plus the reply's opening up to the letter) and
    the index of its correct letter (0 = A, 1 = B); also the two letter token ids. Checks that
    each letter is one token appended to the prompt's tokens, so the position is exact."""
    out, letter_ids, too_long = [], None, 0
    for r in rows:
        text = tok.apply_chat_template(r["prompt"], tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False) + CHOICE_PREFIX
        ids = tok(text, add_special_tokens=False).input_ids
        if letter_ids is None:
            letter_ids = []
            for letter in "AB":
                full = tok(text + letter, add_special_tokens=False).input_ids
                if full[:-1] != ids:
                    raise SystemExit(f"letter {letter} does not tokenize as one token after the prefix")
                letter_ids.append(full[-1])
            print("choice: prompt ends", repr(text[-80:]), "letter ids", letter_ids)
        if len(ids) > max_length:
            too_long += 1
            continue
        out.append({"input_ids": ids, "label": "AB".index(r["correct_letter"])})
    print(f"choice: {len(rows)} rows, {len(out)} within {max_length} tokens ({too_long} dropped), "
          f"correct A {sum(o['label'] == 0 for o in out)}")
    return out, letter_ids


def choice_trainer(model, cfg, ds, letter_ids):
    """Trainer whose loss is the two-way cross-entropy on the letter at the last position;
    logs the running share of rows where the correct letter has the higher probability."""
    import torch
    from transformers import Trainer

    class ChoiceTrainer(Trainer):
        hits = []

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            # the loss below is a per-row mean: let Trainer divide it by the accumulation steps
            # (it skips that for models whose forward takes loss kwargs)
            self.model_accepts_loss_kwargs = False

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            ids = inputs["input_ids"]
            kw = dict(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False)
            try:
                logits = model(**kw, logits_to_keep=1).logits[:, -1]
            except TypeError:  # forward without logits_to_keep
                logits = model(**kw).logits[:, -1]
            two = logits[:, letter_ids].float()
            labels = inputs["labels"].to(two.device)
            loss = torch.nn.functional.cross_entropy(two, labels)
            ChoiceTrainer.hits += (two.argmax(-1) == labels).tolist()
            return (loss, {"logits": two}) if return_outputs else loss

        def log(self, logs, *a, **k):
            if ChoiceTrainer.hits and "loss" in logs:
                logs["choice_acc"] = round(sum(ChoiceTrainer.hits) / len(ChoiceTrainer.hits), 4)
                ChoiceTrainer.hits = []
            super().log(logs, *a, **k)

    def collate(batch):
        if len(batch) != 1:
            raise SystemExit("choice stage runs with --batch 1 (rows are not padded)")
        return {"input_ids": torch.tensor([batch[0]["input_ids"]]),
                "labels": torch.tensor([batch[0]["label"]])}

    return ChoiceTrainer(model=model, args=cfg, train_dataset=ds, data_collator=collate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["sft", "dpo", "choice", "choice_mt", "choice_reason"])
    ap.add_argument("--data", required=True, help="choice / choice_mt: choice.jsonl; choice_reason: dpo.jsonl")
    ap.add_argument("--sft-data", help="choice_mt: sft.jsonl (the judge's own right reasoning)")
    ap.add_argument("--weight", type=float, default=0.25,
                    help="choice_mt / choice_reason: weight of the next-token loss on reasoning")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--init", help="dpo: the SFT adapter to start from (and to use as reference); "
                                   "without it, DPO starts from the base")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--lr", type=float, help="default 1e-4 for sft and choice, 5e-6 for dpo")
    ap.add_argument("--epochs", type=float, default=None, help="default 2 for sft, 1 for dpo")
    ap.add_argument("--beta", type=float, default=0.1, help="dpo")
    ap.add_argument("--max-length", type=int, default=12288, help="longer rows are dropped")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--save-steps", type=int, default=5)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--limit", type=int, help="use a random subset of this many rows")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--experts", default="grouped_mm", choices=["grouped_mm", "eager", "batched_mm"],
                    help="transformers MoE experts implementation (its default is grouped_mm)")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForImageTextToText, AutoTokenizer
    from transformers.trainer_utils import get_last_checkpoint

    rows = load_rows(args.data, args.limit, args.seed)
    tok = AutoTokenizer.from_pretrained(args.base)
    if args.stage == "choice":
        kept, letter_ids = choice_rows(tok, rows, args.max_length)
    elif args.stage == "choice_mt":
        if not args.sft_data:
            raise SystemExit("choice_mt needs --sft-data")
        kept, letter_ids = mt_rows(tok, rows, load_rows(args.sft_data, args.limit, args.seed), args.max_length)
    elif args.stage == "choice_reason":
        kept, letter_ids = reason_rows(tok, rows, args.max_length)
    else:
        if args.stage == "sft":
            data = [{"prompt": r["messages"][:-1], "completion": r["messages"][-1:]} for r in rows]
            check_template(tok, data[0]["prompt"], data[0]["completion"])
        else:
            data = [{"prompt": r["prompt"], "chosen": r["chosen"], "rejected": r["rejected"]} for r in rows]
            check_template(tok, data[0]["prompt"], data[0]["chosen"])

        def length(r):
            replies = [r["completion"]] if "completion" in r else [r["chosen"], r["rejected"]]
            return max(len(tok(tok.apply_chat_template(r["prompt"] + m, tokenize=False),
                               add_special_tokens=False).input_ids) for m in replies)
        kept = [r for r in data if length(r) <= args.max_length]
        print(f"{args.stage}: {len(rows)} rows, {len(kept)} within {args.max_length} tokens")
    ds = Dataset.from_list(kept)

    model = AutoModelForImageTextToText.from_pretrained(
        args.base, dtype=torch.bfloat16, device_map=device_map(args.base), experts_implementation=args.experts)
    model.config.use_cache = False
    out = Path(args.out)
    epochs = args.epochs or (1 if args.stage == "dpo" else 2)
    steps = args.max_steps if args.max_steps > 0 else math.ceil(len(ds) * epochs / (args.batch * args.accum))
    common = dict(output_dir=str(out), per_device_train_batch_size=args.batch,
                  gradient_accumulation_steps=args.accum, bf16=True, logging_steps=5,
                  save_steps=args.save_steps, save_total_limit=3, max_steps=args.max_steps,
                  num_train_epochs=epochs, lr_scheduler_type="cosine", report_to="none",
                  warmup_steps=max(1, round(0.03 * steps)),
                  gradient_checkpointing=True, max_length=args.max_length, seed=args.seed,
                  gradient_checkpointing_kwargs={"use_reentrant": False},
                  # no MoE load-balancing loss: the router is not trained, and with the model
                  # spread over two GPUs TRL adds that loss across devices and fails
                  router_aux_loss_coef=0.0)

    if args.stage in ("choice", "choice_mt", "choice_reason"):
        from transformers import TrainingArguments
        model = get_peft_model(model, LoraConfig(
            r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05,
            target_modules=target_modules(model), task_type="CAUSAL_LM"))
        trl_only = ("max_length", "router_aux_loss_coef")
        cfg = TrainingArguments(learning_rate=args.lr or 1e-4, remove_unused_columns=False,
                                **{k: v for k, v in common.items() if k not in trl_only})
        trainer = (choice_trainer(model, cfg, ds, letter_ids) if args.stage == "choice"
                   else two_loss_trainer(model, cfg, ds, letter_ids, args.stage, args.weight))
        if args.stage == "choice_reason":
            # identity check before training: after the right sample's reasoning the untrained judge
            # writes the correct letter (that is what the sample concluded); a broken forward does not
            dev = model.get_input_embeddings().weight.device
            agree = 0
            with torch.no_grad():
                for r in kept[:8]:
                    x = torch.tensor([r["right_ids"]], device=dev)
                    two = tail_logits(model, x, 1)[-1, letter_ids]
                    agree += int(two.argmax().item() == r["label"])
            print(f"identity check: correct letter after the right reasoning on {agree}/8", flush=True)
            if agree < 7:
                raise SystemExit("identity check failed: the forward pass does not reproduce the judge")
    elif args.stage == "sft":
        from trl import SFTConfig, SFTTrainer
        model = get_peft_model(model, LoraConfig(
            r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05,
            target_modules=target_modules(model), task_type="CAUSAL_LM"))
        cfg = SFTConfig(learning_rate=args.lr or 1e-4, completion_only_loss=True, **common)
        trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
    else:
        from trl import DPOConfig, DPOTrainer
        if args.init:
            model = PeftModel.from_pretrained(model, args.init).merge_and_unload()
        model = get_peft_model(model, LoraConfig(
            r=args.rank, lora_alpha=args.alpha, lora_dropout=0.05,
            target_modules=target_modules(model), task_type="CAUSAL_LM"))
        cfg = DPOConfig(learning_rate=args.lr or 5e-6, beta=args.beta, **common)
        trainer = DPOTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
    model.print_trainable_parameters()

    from transformers import TrainerCallback

    class StopOnNan(TrainerCallback):
        # DPO at lr 1.5e-4 went to NaN within 5 steps and then trained on NaN to the end,
        # which wrote a merged judge that only emits "!"; fail before that step is saved
        def on_log(self, _args, state, _control, logs=None, **kw):
            bad = [k for k in ("loss", "grad_norm") if k in (logs or {})
                   and not (math.isfinite(float(logs[k])) and float(logs[k]) < 1e4)]
            if bad:
                raise RuntimeError(f"training diverged at step {state.global_step}: {logs}")
    trainer.add_callback(StopOnNan())

    last = get_last_checkpoint(str(out)) if out.exists() else None
    if last:
        print("resuming from", last)
    if last and args.stage == "dpo":
        # DPOTrainer keeps a frozen copy of the adapter as the reference ("ref", saved in a
        # subfolder), and on resume Trainer restores only subfolder adapters: the trained
        # one, at the checkpoint's root, would restart from scratch
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file
        state = load_file(f"{last}/adapter_model.safetensors")
        res = set_peft_model_state_dict(trainer.model, state, adapter_name="default")
        if res.unexpected_keys:
            raise SystemExit(f"checkpoint adapter does not fit the model: {res.unexpected_keys[:3]}")
        print(f"restored {len(state)} adapter tensors")
    trainer.train(resume_from_checkpoint=last)
    print("peak GiB per GPU:", [round(torch.cuda.max_memory_allocated(i) / 2**30, 1)
                                for i in range(torch.cuda.device_count())])
    final = out / "final"
    if args.stage in ("sft", "choice", "choice_mt", "choice_reason"):
        trainer.model.save_pretrained(str(final))
    else:
        trainer.model.save_pretrained(str(out / "dpo_only"))
        if args.init:
            join_adapters(Path(args.init), out / "dpo_only", final)
        else:
            trainer.model.save_pretrained(str(final))
    tok.save_pretrained(str(final))
    (final / "train_args.json").write_text(json.dumps(vars(args), indent=1) + "\n")
    print("adapter:", final)


if __name__ == "__main__":
    main()
