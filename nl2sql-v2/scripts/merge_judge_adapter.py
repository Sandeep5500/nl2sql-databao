#!/usr/bin/env python3
"""Fold a judge adapter (train_judge_lora.py) into the AWQ serving checkpoint.

vLLM 0.18.1 cannot serve LoRA on this model's AWQ build: enabling LoRA wraps the
routed-expert layer, and its LoRA support needs unquantized (Triton) experts while the AWQ
build runs Marlin ones (an assertion fails at startup, whatever the adapter targets). The
adapter only touches modules the AWQ build stores unquantized (attention, linear
attention, shared experts), so it is added to those weights exactly, W += (alpha / r) B A,
and the result is an AWQ checkpoint like the original, served the same way. Routed
experts are untouched; shards without a changed weight are linked, not copied.

Usage:
    python scripts/merge_judge_adapter.py --adapter ../results/judge_train/dpo/final \\
        --out ../results/judge_train/judge_awq [--base QuantTrio/Qwen3.6-35B-A3B-AWQ]
then serve --out with the same vLLM flags as the base.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

PREFIX = "base_model.model."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="QuantTrio/Qwen3.6-35B-A3B-AWQ",
                    help="a checkpoint directory, or a repo id already in the HF cache")
    args = ap.parse_args()

    import torch
    from safetensors import safe_open
    from safetensors.torch import load_file, save_file

    base = Path(args.base)
    if not base.is_dir():  # the cached snapshot (snapshot_download refuses one without repo metadata files)
        from huggingface_hub import try_to_load_from_cache
        config = try_to_load_from_cache(args.base, "config.json")
        if not isinstance(config, str):
            raise SystemExit(f"{args.base} is not in the HF cache")
        base = Path(config).parent
    adapter, out = Path(args.adapter), Path(args.out)
    cfg = json.loads((adapter / "adapter_config.json").read_text())
    scale = cfg["lora_alpha"] / cfg["r"]
    lora = load_file(str(adapter / "adapter_model.safetensors"))
    deltas = {}  # checkpoint key -> (A, B)
    for k in lora:
        if k.endswith(".lora_A.weight"):
            module = k[len(PREFIX):-len(".lora_A.weight")]
            deltas[module + ".weight"] = (lora[k], lora[k.replace(".lora_A.", ".lora_B.")])
    index = json.loads((base / "model.safetensors.index.json").read_text())["weight_map"]
    missing = [k for k in deltas if k not in index]
    if missing:
        raise SystemExit(f"{len(missing)} adapter targets are not in the checkpoint, e.g. {missing[:3]}")

    out.mkdir(parents=True, exist_ok=True)
    for f in base.iterdir():
        if not f.name.endswith(".safetensors"):  # configs, tokenizer, index
            # the HF cache files are read-only and shutil.copy keeps that mode, so a rerun
            # after an interrupted merge could not overwrite them
            (out / f.name).unlink(missing_ok=True)
            shutil.copyfile(f, out / f.name)
    changed, worst = 0, 0.0
    for shard in sorted(set(index.values())):
        keys = [k for k in deltas if index[k] == shard]
        dest = out / shard
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        if not keys:
            os.symlink(os.path.realpath(base / shard), dest)
            continue
        with safe_open(str(base / shard), "pt") as fh:
            meta = fh.metadata()
        tensors = load_file(str(base / shard))
        for k in keys:
            a, b = deltas[k]
            w = tensors[k]
            d = scale * (b.float() @ a.float())
            if d.shape != w.shape:
                raise SystemExit(f"{k}: delta {tuple(d.shape)} vs weight {tuple(w.shape)}")
            tensors[k] = (w.float() + d).to(w.dtype).contiguous()
            worst = max(worst, ((tensors[k].float() - w.float()) - d).abs().max().item())
            changed += 1
        save_file(tensors, str(dest), metadata=meta)
    (out / "merged_adapter.json").write_text(json.dumps(
        {"base": str(base), "adapter": str(adapter.resolve()), "scale": scale,
         "weights_changed": changed}, indent=1) + "\n")
    print(f"merged {changed} weights into {out} (largest rounding error {worst:.2e})")


if __name__ == "__main__":
    main()
