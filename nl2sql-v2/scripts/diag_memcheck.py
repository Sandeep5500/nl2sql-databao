#!/usr/bin/env python3
"""Run under compute-sanitizer memcheck (with PYTORCH_NO_CUDA_MEMORY_CACHING=1, so every tensor is its
own allocation): does any kernel of the deployed architecture read or write out of bounds? The C1 crash
of Nov 13 was a kernel fault (error 719), and the silent zeros / NaN / garbage of the morning would fit
a kernel that reads past its tensors into mapped memory.

A 4-layer model at the real dimensions (3 linear-attention layers on the fla gated-delta kernels, 1
full-attention layer, the 256-expert MoE on grouped_mm, the real vocabulary), random bf16 weights,
frozen; forward and backward with gradient checkpointing as in training (the gradient flows to the
input embeddings, through every kernel), at sequence lengths that are and are not multiples of 64.

    compute-sanitizer --tool memcheck python scripts/diag_memcheck.py 1016 2580 8191 12001
"""
import sys

import torch
from transformers import AutoConfig, AutoModelForImageTextToText

cfg = AutoConfig.from_pretrained("Qwen/Qwen3.6-35B-A3B")
tc = cfg.text_config
tc.num_hidden_layers, tc.layer_types = 4, ["linear_attention"] * 3 + ["full_attention"]
cfg.vision_config.depth = 1
torch.manual_seed(0)
with torch.device("cuda"):
    model = AutoModelForImageTextToText.from_config(cfg, dtype=torch.bfloat16)
model.requires_grad_(False)
model.enable_input_require_grads()
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.train()
print("gpu", torch.cuda.get_device_name(0), "experts", getattr(tc, "_experts_implementation", None), flush=True)
for T in [int(a) for a in sys.argv[1:]] or [1016, 2580, 8191, 12001]:
    ids = torch.randint(0, tc.vocab_size, (1, T), device="cuda")
    out = model.model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False)
    h = out[0]
    loss = model.lm_head(h[0, -64:]).float().logsumexp(-1).mean()
    loss.backward()
    torch.cuda.synchronize()
    print(f"T={T}: loss {float(loss):.4f}, |h| max {float(h.abs().max()):.3g}, finite {bool(torch.isfinite(h).all())}",
          flush=True)
print("memcheck run complete", flush=True)
