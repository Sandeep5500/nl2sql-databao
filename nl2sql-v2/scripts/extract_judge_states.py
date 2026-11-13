#!/usr/bin/env python3
"""Hidden states of the untuned judge after its own stored reasoning, for the trace-verification
probe (documents/head_probe_prereg.md, Stage A).

Each stored practice judgment (sample_judge_verdicts.py output: pairs[].prompt, pairs[].samples[]
with the full reasoning) is rebuilt token for token as the judge produced it:
    chat template (thinking on) + "<think>\\n" + reasoning.strip() + "\\n</think>\\n\\n" + '{"winner": "'
and run through the bf16 model once (no generation). Read out, for the output of decoder layers
--layers and of the final norm (what lm_head reads):
    the verdict position (the last input token, which predicts the letter), the </think> token,
    the mean over the reasoning tokens, and the reasoning token at 25 / 50 / 75%
plus logit(A) - logit(B) at the verdict position. Identity check: that difference must have the
sign of the stored verdict; the run stops if it disagrees on more than 3% of the first 100.

Output: --out-dir/shard_<n>.npz (feats float16 [n, layers+1, 6, hidden], z float32 [n]) and
shard_<n>.jsonl (one metadata line per row). Shards are written whole, so a preempted run resumes
by skipping the shards that exist; --worker k --workers n splits the shards between jobs.

Usage (GPU node, the bf16 base spread over the visible GPUs):
    python scripts/extract_judge_states.py --verdicts <file> [<file> ...] --out-dir <dir>
        [--limit 20] [--worker 0 --workers 2]
"""

import argparse
import json
import os
from pathlib import Path

BASE = "Qwen/Qwen3.6-35B-A3B"
OPENING = '{"winner": "'  # the thinking judge's reply opening in 10,710 of 10,715 stored answers
POSITIONS = ["verdict", "think_end", "reason_mean", "reason_25", "reason_50", "reason_75"]


def items(paths, limit):
    """One row per usable stored sample: verdict A/B, no error, not truncated, reasoning kept."""
    out = []
    for path in paths:
        tag = Path(path).stem.removeprefix("verdicts_")
        for line in open(path):
            r = json.loads(line)
            for pi, p in enumerate(r["pairs"]):
                for si, s in enumerate(p["samples"]):
                    if s.get("error") or s.get("truncated") or s.get("verdict") not in ("A", "B") \
                            or not (s.get("reasoning") or "").strip():
                        continue
                    out.append(dict(file=tag, instance_id=r["instance_id"], db=r["db"], split=r["split"],
                                    source=r["source"], pair=pi, first=p["first"], second=p["second"],
                                    sample=si, correct_letter=p["correct_letter"], verdict=s["verdict"],
                                    right=s["verdict"] == p["correct_letter"],
                                    reasoning_chars=len(s["reasoning"]), prompt=p["prompt"],
                                    reasoning=s["reasoning"]))
                    if limit and len(out) >= limit:
                        return out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--layers", default="9,19,29", help="0-based decoder layers whose output is read "
                                                        "(the final norm output is always read)")
    ap.add_argument("--shard-size", type=int, default=200)
    ap.add_argument("--max-tokens", type=int, default=16384, help="longer rows are skipped and listed")
    ap.add_argument("--limit", type=int, default=0, help="first N rows only (smoke test)")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--experts", default="grouped_mm", choices=["grouped_mm", "eager", "batched_mm"],
                    help="transformers MoE experts implementation (its default is grouped_mm)")
    args = ap.parse_args()

    import numpy as np
    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    rows = items(args.verdicts, args.limit)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shards = [list(range(i, min(i + args.shard_size, len(rows)))) for i in range(0, len(rows), args.shard_size)]
    todo = [n for n in range(len(shards)) if n % args.workers == args.worker
            and not (out_dir / f"shard_{n:05d}.npz").exists()]
    print(f"{len(rows)} rows in {len(shards)} shards; worker {args.worker}/{args.workers}: {len(todo)} to do",
          flush=True)
    if not todo:
        return

    tok = AutoTokenizer.from_pretrained(args.base)
    think_end_id = tok.convert_tokens_to_ids("</think>")
    letter_ids = None

    def encode(row):
        nonlocal letter_ids
        gen = tok.apply_chat_template([{"role": "user", "content": row["prompt"]}], tokenize=False,
                                      add_generation_prompt=True, enable_thinking=True)
        if not gen.endswith("<think>\n"):
            raise SystemExit(f"generation prompt does not end with '<think>\\n': {gen[-60:]!r}")
        text = gen + row["reasoning"].strip() + "\n</think>\n\n" + OPENING
        ids = tok(text, add_special_tokens=False).input_ids
        gen_ids = tok(gen, add_special_tokens=False).input_ids
        if ids[:len(gen_ids)] != gen_ids:
            raise SystemExit("the generation prompt does not tokenize as a prefix of the rebuilt text")
        if letter_ids is None:
            letter_ids = []
            for letter in "AB":
                full = tok(text + letter, add_special_tokens=False).input_ids
                if full[:-1] != ids:
                    raise SystemExit(f"letter {letter} is not one token after the reply opening")
                letter_ids.append(full[-1])
            print("letter ids", letter_ids, "text ends", repr(text[-60:]), flush=True)
        t_end = len(ids) - 1 - ids[::-1].index(think_end_id)
        r0, r1 = len(gen_ids), t_end  # reasoning tokens (the '\n' before </think> included)
        pos = [len(ids) - 1, t_end] + [r0 + int(f * (r1 - r0)) for f in (0.25, 0.5, 0.75)]
        return ids, pos, (r0, r1)

    gib = 2 ** 30
    n_gpu = torch.cuda.device_count()
    max_memory = {i: int(torch.cuda.get_device_properties(i).total_memory * 0.92) - (4 * gib if i == 0 else 0)
                  for i in range(n_gpu)}
    model = AutoModelForImageTextToText.from_pretrained(args.base, dtype=torch.bfloat16, device_map="auto",
                                                        max_memory=max_memory, experts_implementation=args.experts)
    model.eval()
    layer_list = norm = None
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.ModuleList) and len(mod) and "DecoderLayer" in type(mod[0]).__name__:
            layer_list, norm = mod, model.get_submodule(name.rsplit(".", 1)[0] + ".norm")
            break
    if layer_list is None:
        raise SystemExit("decoder layers not found")
    layers = [int(x) for x in args.layers.split(",")]
    print(f"{len(layer_list)} decoder layers; reading outputs of {layers} and the final norm", flush=True)

    grab = {}
    cur = {}

    def make_hook(key):
        def hook(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            pos, (r0, r1) = cur["pos"], cur["span"]
            picked = h[0, pos].float()
            mean = h[0, r0:r1].float().mean(0, keepdim=True)
            grab[key] = torch.cat([picked[:2], mean, picked[2:]]).cpu()  # order = POSITIONS
        return hook

    handles = [layer_list[i].register_forward_hook(make_hook(i)) for i in layers]
    handles.append(norm.register_forward_hook(make_hook("norm")))
    keys = layers + ["norm"]
    cfg = model.config
    hidden = getattr(cfg, "hidden_size", None) or cfg.text_config.hidden_size
    dev0 = model.get_input_embeddings().weight.device
    seen = agree = 0
    for n in todo:
        feats, zs, meta = [], [], []
        for i in shards[n]:
            row = rows[i]
            ids, pos, span = encode(row)
            m = {k: v for k, v in row.items() if k not in ("prompt", "reasoning")}
            m.update(row=i, tokens=len(ids), reason_tokens=span[1] - span[0])
            if len(ids) > args.max_tokens:
                m["skipped"] = "too long"
                meta.append(m)
                feats.append(np.zeros((len(keys), len(POSITIONS), hidden), np.float16))
                zs.append(np.nan)
                continue
            cur["pos"], cur["span"] = pos, span
            with torch.no_grad():
                x = torch.tensor([ids], device=dev0)
                logits = model(input_ids=x, attention_mask=torch.ones_like(x), use_cache=False,
                               logits_to_keep=1).logits[0, -1]
            z = float(logits[letter_ids[0]] - logits[letter_ids[1]])
            feats.append(torch.stack([grab[k] for k in keys]).numpy().astype(np.float16))
            zs.append(z)
            meta.append(m)
            seen += 1
            agree += (z > 0) == (row["verdict"] == "A")
            if seen == 100 and agree < 97:
                raise SystemExit(f"identity check failed: readout sign matches the stored verdict on {agree}/100")
        tmp = out_dir / f"shard_{n:05d}.tmp.npz"
        np.savez(tmp, feats=np.stack(feats), z=np.array(zs, np.float32))
        with open(out_dir / f"shard_{n:05d}.jsonl", "w") as f:
            for m in meta:
                f.write(json.dumps(m) + "\n")
        os.replace(tmp, out_dir / f"shard_{n:05d}.npz")
        print(f"shard {n} done: {len(meta)} rows; identity {agree}/{seen}", flush=True)
    for h in handles:
        h.remove()


if __name__ == "__main__":
    main()
