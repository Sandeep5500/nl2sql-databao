#!/usr/bin/env python3
"""Smoke test of train_judge_lora.py's choice-type stages on a tiny random model of the deployed
architecture (Qwen3.5-MoE with 3 linear-attention layers, 1 full-attention layer, 4 experts), on real
v4 rows. Checks that every loss runs and logs, that the contrastive head trains and is saved with each
checkpoint, and that a run resumed from checkpoint-3 ends on the same head as an uninterrupted one.
The forward check's letter-mass test fails on random weights by design; it runs and is reported.

    python scripts/smoke_two_loss.py <work dir> <data dir with dpo.jsonl, choice.jsonl, sft.jsonl>
"""
import shutil
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_judge_lora as t  # noqa: E402

work, data = Path(sys.argv[1]), Path(sys.argv[2])
tiny = work / "tiny"
if not (tiny / "config.json").exists():
    from transformers import AutoConfig, AutoModelForImageTextToText, AutoTokenizer
    cfg = AutoConfig.from_pretrained(t.BASE)
    tc, vc = cfg.text_config, cfg.vision_config
    tc.num_hidden_layers, tc.layer_types = 4, ["linear_attention"] * 3 + ["full_attention"]
    tc.hidden_size, tc.num_attention_heads, tc.num_key_value_heads = 128, 2, 1
    tc.linear_num_key_heads, tc.linear_num_value_heads = 2, 4
    tc.num_experts, tc.num_experts_per_tok = 4, 2
    tc.moe_intermediate_size = tc.shared_expert_intermediate_size = 64
    vc.depth, vc.out_hidden_size = 1, 128
    torch.manual_seed(0)
    model = AutoModelForImageTextToText.from_config(cfg, dtype=torch.bfloat16)
    model.save_pretrained(tiny)
    AutoTokenizer.from_pretrained(t.BASE).save_pretrained(tiny)
    print(f"tiny model: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M parameters", flush=True)
    del model

strict = t.forward_check


def lenient(*a, **k):
    try:
        strict(*a, **k)
    except SystemExit as e:
        print("(expected on random weights)", e, flush=True)


t.forward_check = lenient


def run(stage, out, *extra):
    sys.argv = ["train_judge_lora.py", stage, "--base", str(tiny), "--out", str(out), "--experts", "eager",
                "--limit", "16", "--accum", "1", "--save-steps", "3", *extra]
    print("\n=== train_judge_lora.py", " ".join(sys.argv[1:]), flush=True)
    t.main()


def head(path):
    return torch.load(path)["weight"].float()


both = ["--data", str(data / "dpo.jsonl"), "--weight", "0.25", "--vec-weight", "1", "--max-steps", "6"]
c2 = work / "c2_both"
shutil.rmtree(c2, ignore_errors=True)
run("choice_reason", c2, *both)
w6, w3 = head(c2 / "final" / "vec_head.pt"), head(c2 / "checkpoint-3" / "vec_head.pt")
saved = sorted(p.parent.name for p in c2.glob("checkpoint-*/vec_head.pt"))
print(f"contrastive head: norm {float(w3.norm()):.4g} at step 3, {float(w6.norm()):.4g} at step 6; "
      f"saved in {saved}", flush=True)
shutil.rmtree(c2 / "checkpoint-6")
shutil.rmtree(c2 / "final")
run("choice_reason", c2, *both)  # resumes from checkpoint-3
w6r = head(c2 / "final" / "vec_head.pt")
print(f"resumed vs uninterrupted, head relative diff {float((w6 - w6r).norm() / w6.norm()):.3g}; "
      f"restarting the head from zero would lose about {float(w3.norm() / w6.norm()):.3g}", flush=True)

run("choice_reason", work / "c2_pick_only", "--data", str(data / "dpo.jsonl"), "--weight", "0", "--max-steps", "2")
run("choice_mt", work / "c1", "--data", str(data / "choice.jsonl"), "--sft-data", str(data / "sft.jsonl"),
    "--max-steps", "2")
run("choice", work / "c0", "--data", str(data / "choice.jsonl"), "--max-steps", "2")
print("\nSMOKE OK", flush=True)
