#!/usr/bin/env python3
"""Does a direct GPU-to-GPU copy deliver the right bytes on this node? The bf16 judge model split
across 2 GPUs (HF device_map) intermittently computes exact zeros while one-GPU runs (vLLM, single MoE
block) are fine. Copies tensors cuda:0 -> cuda:1 directly (peer-to-peer when enabled, blocking and
non-blocking) and through the CPU, many times and sizes, and reports mismatches; also the peer-access
flag. Every failing run had PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True, so the test runs twice,
without and with it, and grows, frees and empties the memory pool between copies so the expandable
segments map and unmap memory as they do under a model's activations. Seconds, no model."""
import os
import subprocess
import sys

if os.environ.get("P2P_CHILD") is None:
    try:
        print(subprocess.run(["nvidia-smi", "topo", "-m"], capture_output=True, text=True).stdout, flush=True)
    except Exception as e:
        print("topo:", e)
    for alloc in ("", "expandable_segments:True"):
        env = {**os.environ, "P2P_CHILD": "1", "PYTORCH_CUDA_ALLOC_CONF": alloc}
        subprocess.run([sys.executable, __file__], env=env)
    sys.exit(0)

import torch  # noqa: E402

alloc = os.environ.get("PYTORCH_CUDA_ALLOC_CONF") or "default"
print(f"[alloc={alloc}] gpus", [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
      "peer access 0->1:", torch.cuda.can_device_access_peer(0, 1), "1->0:", torch.cuda.can_device_access_peer(1, 0),
      flush=True)
w = torch.randn(2048, 2048, device="cuda:0", dtype=torch.bfloat16) / 45
bad = total = 0
for n in range(300):
    if n % 3 == 0:  # grow the pool on both GPUs, then free it (and every 30 copies, return it)
        big = [torch.empty((1 + n % 4) * 2**30, dtype=torch.uint8, device=f"cuda:{d}") for d in (0, 1)]
        del big
        if n % 30 == 0:
            torch.cuda.empty_cache()
    rows = [1, 7, 1016, 2580, 4097, 12000][n % 6]
    src = n % 2  # both directions
    dst = 1 - src
    x = torch.randn(rows, 2048, device=f"cuda:{src}", dtype=torch.bfloat16)
    y = x @ w.to(f"cuda:{src}")  # a computed tensor, as a layer's output would be
    staged = y.cpu().to(f"cuda:{dst}")
    for mode, got in (("blocking", y.to(f"cuda:{dst}")), ("non-blocking", y.to(f"cuda:{dst}", non_blocking=True))):
        total += 1
        torch.cuda.synchronize(dst)
        if not torch.equal(got, staged):
            bad += 1
            if bad <= 5:
                print(f"[alloc={alloc}] MISMATCH copy {n} {src}->{dst} {mode} rows {rows}: zero-frac "
                      f"{float((got == 0).float().mean()):.3f} max|diff| {float((got.float() - staged.float()).abs().max()):.3g}",
                      flush=True)
print(f"RESULT [alloc={alloc}] {bad}/{total} direct copies differ from CPU-staged copies", flush=True)
