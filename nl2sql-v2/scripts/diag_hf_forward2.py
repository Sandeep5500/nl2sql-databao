#!/usr/bin/env python3
"""Second diagnostic: the extraction job's identity check failed (~55/100) while a plain HF forward of the
same rows passes 24/24. Same model and rows, four call variants: plain; logits_to_keep=1; the extraction's
forward hooks attached; hooks + logits_to_keep=1. Also checks that the hooked final-norm state at the
verdict position times (W_A - W_B) reproduces logit A - logit B."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "judge-tmp"))
from extract_judge_states import OPENING, items

import torch
from transformers import AutoModelForImageTextToText, AutoTokenizer

BASE = "Qwen/Qwen3.6-35B-A3B"
tok = AutoTokenizer.from_pretrained(BASE)
rows = items(["/data/user_data/dpalagan/judge-data/results/judge_train/verdicts_train_v1.jsonl"], 24)
think_end = tok.convert_tokens_to_ids("</think>")
seqs = []
for r in rows:
    gen = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}], tokenize=False,
                                  add_generation_prompt=True, enable_thinking=True)
    g0 = len(tok(gen, add_special_tokens=False).input_ids)
    ids = tok(gen + r["reasoning"].strip() + "\n</think>\n\n" + OPENING, add_special_tokens=False).input_ids
    t_end = len(ids) - 1 - ids[::-1].index(think_end)
    pos = [len(ids) - 1, t_end] + [g0 + int(f * (t_end - g0)) for f in (0.25, 0.5, 0.75)]
    seqs.append((ids, pos, (g0, t_end), r["verdict"]))
la, lb = tok.convert_tokens_to_ids("A"), tok.convert_tokens_to_ids("B")
gib = 2 ** 30
mm = {i: int(torch.cuda.get_device_properties(i).total_memory * 0.92) - (4 * gib if i == 0 else 0)
      for i in range(torch.cuda.device_count())}
model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16, device_map="auto", max_memory=mm)
model.eval()
layer_list = norm = None
for name, mod in model.named_modules():
    if isinstance(mod, torch.nn.ModuleList) and len(mod) and "DecoderLayer" in type(mod[0]).__name__:
        layer_list, norm = mod, model.get_submodule(name.rsplit(".", 1)[0] + ".norm")
        print("decoder list", name, len(mod), "norm", name.rsplit(".", 1)[0] + ".norm", flush=True)
        break
dev = model.get_input_embeddings().weight.device
grab, cur = {}, {}

def make_hook(key):
    def hook(mod, inp, out):
        h = out[0] if isinstance(out, tuple) else out
        pos, (r0, r1) = cur["pos"], cur["span"]
        picked = h[0, pos].float()
        mean = h[0, r0:r1].float().mean(0, keepdim=True)
        grab[key] = torch.cat([picked[:2], mean, picked[2:]]).cpu()
        grab[str(key) + "_type"] = (type(out).__name__, tuple(h.shape))
    return hook

w = model.get_output_embeddings().weight
wdiff = (w[la] - w[lb]).float().cpu()

def run(name, keep, hooks):
    handles = []
    if hooks:
        handles = [layer_list[i].register_forward_hook(make_hook(i)) for i in (9, 19, 29)]
        handles.append(norm.register_forward_hook(make_hook("norm")))
    agree, zs, zh = 0, [], []
    with torch.no_grad():
        for ids, pos, span, verdict in seqs:
            cur["pos"], cur["span"] = pos, span
            x = torch.tensor([ids], device=dev)
            kw = dict(input_ids=x, attention_mask=torch.ones_like(x), use_cache=False)
            if keep:
                kw["logits_to_keep"] = 1
            lg = model(**kw).logits[0, -1].float()
            z = float(lg[la] - lg[lb])
            zs.append(z)
            agree += (z > 0) == (verdict == "A")
            if hooks:
                zh.append(float(grab["norm"][0] @ wdiff))
    for h in handles:
        h.remove()
    extra = ""
    if hooks:
        extra = f"; hooked final-norm verdict-position state . (W_A-W_B) first 4: {[round(v, 2) for v in zh[:4]]}; " \
                f"layer out type {grab.get('9_type')} norm out type {grab.get('norm_type')}"
    print(f"[{name}] identity {agree}/{len(seqs)}; z first 4 {[round(v, 2) for v in zs[:4]]}{extra}", flush=True)

run("plain", False, False)
run("logits_to_keep=1", True, False)
run("hooks", False, True)
run("hooks + logits_to_keep=1", True, True)
