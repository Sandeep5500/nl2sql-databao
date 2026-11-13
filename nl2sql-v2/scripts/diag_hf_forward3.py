#!/usr/bin/env python3
"""Third diagnostic: the bf16 HF forward of Qwen3.6-35B-A3B is intermittently broken (one job: identity
24/24 and ' Paris'; a later job on the same node and code: logit gaps of exactly 0.0 / NaN, final-norm
states of 0). Localize it: the device map (anything on CPU?), the first decoder layer whose output is
non-finite or all-zero, and whether repeating the same forward gives the same result; then the same
with the pure-torch gated-delta rule, and with expandable segments off for comparison (set by the
caller via PYTORCH_CUDA_ALLOC_CONF)."""
import os
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path.home() / "judge-tmp"))
from extract_judge_states import OPENING, items

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer

BASE = "Qwen/Qwen3.6-35B-A3B"
print("CUDA_VISIBLE_DEVICES", os.environ.get("CUDA_VISIBLE_DEVICES"), "alloc conf",
      os.environ.get("PYTORCH_CUDA_ALLOC_CONF"), "torch", torch.__version__, flush=True)
for i in range(torch.cuda.device_count()):
    free, total = torch.cuda.mem_get_info(i)
    print(f"gpu {i}: {torch.cuda.get_device_name(i)} free {free / 2**30:.1f} / {total / 2**30:.1f} GiB", flush=True)
tok = AutoTokenizer.from_pretrained(BASE)
rows = items(["/data/user_data/dpalagan/judge-data/results/judge_train/verdicts_train_v1.jsonl"], 6)
seqs = []
for r in rows:
    gen = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}], tokenize=False,
                                  add_generation_prompt=True, enable_thinking=True)
    seqs.append((tok(gen + r["reasoning"].strip() + "\n</think>\n\n" + OPENING, add_special_tokens=False).input_ids,
                 r["verdict"]))
la, lb = tok.convert_tokens_to_ids("A"), tok.convert_tokens_to_ids("B")
gib = 2 ** 30
mm = {i: int(torch.cuda.get_device_properties(i).total_memory * 0.92) - (4 * gib if i == 0 else 0)
      for i in range(torch.cuda.device_count())}
model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16, device_map="auto", max_memory=mm)
model.eval()
dm = getattr(model, "hf_device_map", {})
print("device map placements:", Counter(str(v) for v in dm.values()), flush=True)
tc = getattr(model.config, "text_config", model.config)
print("experts implementation:", getattr(model.config, "_experts_implementation", None),
      getattr(tc, "_experts_implementation", None), flush=True)
layers = model.model.language_model.layers
types = [type(l.linear_attn).__name__ if hasattr(l, "linear_attn") and l.linear_attn is not None else "full_attn"
         for l in layers]
stats = {}

def make_hook(i):
    def hook(mod, inp, out):
        h = out[0] if isinstance(out, tuple) else out
        stats[i] = (int((~torch.isfinite(h)).sum()), float(h.float().abs().max()), float(h.float().abs().mean()))
    return hook

for i, l in enumerate(layers):
    l.register_forward_hook(make_hook(i))
emb = model.get_input_embeddings()
dev = emb.weight.device

def forward(ids):
    x = torch.tensor([ids], device=dev)
    with torch.no_grad():
        lg = model(input_ids=x, attention_mask=torch.ones_like(x), use_cache=False).logits[0, -1].float()
    return float(lg[la] - lg[lb])

def report(tag):
    agree, first_bad = 0, []
    for n, (ids, verdict) in enumerate(seqs):
        zs = [forward(ids) for _ in range(2)]
        agree += (zs[0] > 0) == (verdict == "A")
        bad = [i for i in range(len(layers)) if stats[i][0] > 0 or stats[i][2] == 0.0]
        first_bad.append(bad[0] if bad else None)
        print(f"  [{tag}] row {n} tokens {len(ids)} z {zs[0]:+.2f} repeat {zs[1]:+.2f} stored {verdict} "
              f"first bad layer {bad[0] if bad else None} ({types[bad[0]] if bad else '-'}); "
              f"layer0 nonfinite/max/mean {stats[0]}; last {stats[len(layers) - 1]}", flush=True)
    print(f"[{tag}] identity {agree}/{len(seqs)}; first bad layers {first_bad}", flush=True)

report("fla gated delta (default experts)")
for impl in ("eager", "batched_mm"):
    model.set_experts_implementation(impl)
    print("experts implementation now:", getattr(tc, "_experts_implementation", None), flush=True)
    report(f"experts={impl}")
model.set_experts_implementation("grouped_mm")
import transformers.models.qwen3_5_moe.modeling_qwen3_5_moe as mq
for mod in model.modules():
    if hasattr(mod, "chunk_gated_delta_rule"):
        mod.chunk_gated_delta_rule = mq.torch_chunk_gated_delta_rule
report("torch gated delta, grouped_mm experts")
x = torch.tensor([tok("The capital of France is", add_special_tokens=False).input_ids], device=dev)
with torch.no_grad():
    print("capital ->", repr(tok.decode([model(input_ids=x, use_cache=False).logits[0, -1].argmax().item()])), flush=True)
