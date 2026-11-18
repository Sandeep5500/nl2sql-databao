#!/usr/bin/env python3
"""Fast check of the suspect in the intermittent HF forward failures: transformers 5.5.3 runs the MoE
experts with torch's fused grouped_mm by default. One Qwen3.6-35B-A3B sparse MoE block at the real
dimensions (256 experts, top-8, hidden 2048), random bf16 weights, on one GPU: the same input through
the grouped_mm, eager and batched_mm experts, each run twice. They must agree (bf16 tolerance) and be
finite; a mismatch or NaN on this GPU confirms the bug without loading the 35B model."""
import os

import torch
from transformers import AutoConfig
from transformers.models.qwen3_5_moe import modeling_qwen3_5_moe as mq

print("gpu", torch.cuda.get_device_name(0), "torch", torch.__version__, "alloc",
      os.environ.get("PYTORCH_CUDA_ALLOC_CONF"), flush=True)
cfg = AutoConfig.from_pretrained("Qwen/Qwen3.6-35B-A3B").text_config
block_cls = next(getattr(mq, n) for n in dir(mq) if n.endswith("SparseMoeBlock"))
torch.manual_seed(0)
block = block_cls(cfg).to("cuda", torch.bfloat16).eval()
for p in block.parameters():
    torch.nn.init.normal_(p, std=0.02)
print(block_cls.__name__, "experts", cfg.num_experts, "top-k", cfg.num_experts_per_tok,
      "hidden", cfg.hidden_size, "moe ff", cfg.moe_intermediate_size, flush=True)

results = {}
for T in (1016, 2580, 4097):
    x = torch.randn(1, T, cfg.hidden_size, device="cuda", dtype=torch.bfloat16)
    for impl in ("eager", "grouped_mm", "batched_mm"):
        block.experts.config._experts_implementation = impl
        outs = []
        for _ in range(2):
            with torch.no_grad():
                o = block(x)
            outs.append((o[0] if isinstance(o, tuple) else o).float())
        results[(T, impl)] = outs[0]
        print(f"T={T} {impl:10s} finite {bool(torch.isfinite(outs[0]).all())} zero-rows "
              f"{int((outs[0].abs().sum(-1) == 0).sum())} repeat max|diff| {float((outs[0] - outs[1]).abs().max()):.3g} "
              f"mean|out| {float(outs[0].abs().mean()):.4g}", flush=True)
    ref = results[(T, "eager")]
    for impl in ("grouped_mm", "batched_mm"):
        d = (results[(T, impl)] - ref).abs()
        print(f"T={T} {impl} vs eager: max|diff| {float(d.max()):.3g}, mean|diff| {float(d.mean()):.3g} "
              f"(relative {float(d.mean() / ref.abs().mean()):.3g})", flush=True)
