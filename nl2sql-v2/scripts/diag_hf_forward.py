#!/usr/bin/env python3
"""Diagnose why the bf16 HF forward of Qwen3.6-35B-A3B disagrees with the served (vLLM, AWQ) judge:
on 24 stored practice judgments the served judge's next letter after '{"winner": "' matches the stored
verdict 24/24, the HF forward used by extract_judge_states.py and train_judge_lora.py only ~55/100.

For each model variant: identity agreement on the 24 judgments, the mean per-token NLL of the judge's
own reasoning (its samples at temperature 0.6 should score low), and a trivial completion.
Variants: AutoModelForImageTextToText (as the trainings load it), the same with the pure-torch gated
delta rule (fla kernel swapped out), and AutoModelForCausalLM.

    python scripts/diag_hf_forward.py --verdicts <verdicts_train_v1.jsonl>
"""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / "judge-tmp"))
from extract_judge_states import OPENING, items  # noqa: E402

BASE = "Qwen/Qwen3.6-35B-A3B"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--n", type=int, default=24)
    args = ap.parse_args()
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer
    print("transformers", transformers.__version__, "torch", torch.__version__, flush=True)

    tok = AutoTokenizer.from_pretrained(BASE)
    rows = items([args.verdicts], args.n)
    seqs = []
    for r in rows:
        gen = tok.apply_chat_template([{"role": "user", "content": r["prompt"]}], tokenize=False,
                                      add_generation_prompt=True, enable_thinking=True)
        gen_ids = tok(gen, add_special_tokens=False).input_ids
        ids = tok(gen + r["reasoning"].strip() + "\n</think>\n\n" + OPENING, add_special_tokens=False).input_ids
        seqs.append((ids, len(gen_ids), r["verdict"]))
    la, lb = tok.convert_tokens_to_ids("A"), tok.convert_tokens_to_ids("B")
    print("letter ids", la, lb, flush=True)

    gib = 2 ** 30
    mm = {i: int(torch.cuda.get_device_properties(i).total_memory * 0.92) - (4 * gib if i == 0 else 0)
          for i in range(torch.cuda.device_count())}

    def run(model, name):
        dev = model.get_input_embeddings().weight.device
        agree, nlls = 0, []
        with torch.no_grad():
            for n, (ids, g0, verdict) in enumerate(seqs):
                x = torch.tensor([ids], device=dev)
                logits = model(input_ids=x, attention_mask=torch.ones_like(x), use_cache=False).logits[0].float()
                z = float(logits[-1, la] - logits[-1, lb])
                agree += (z > 0) == (verdict == "A")
                lp = torch.log_softmax(logits[g0 - 1:-1], -1)  # predictions for the reasoning + tail tokens
                tgt = torch.tensor(ids[g0:], device=lp.device)
                nlls.append(float(-lp.gather(1, tgt[:, None]).mean()))
                if n < 3:
                    print(f"  [{name}] row {n}: tokens {len(ids)} z {z:+.2f} stored {verdict} "
                          f"nll/token {nlls[-1]:.3f}", flush=True)
            q = tok("The capital of France is", add_special_tokens=False).input_ids
            nxt = model(input_ids=torch.tensor([q], device=dev), use_cache=False).logits[0, -1].argmax().item()
        print(f"[{name}] identity {agree}/{len(seqs)}; mean reasoning nll/token {sum(nlls) / len(nlls):.3f}; "
              f"'The capital of France is' -> {tok.decode([nxt])!r}", flush=True)

    model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16, device_map="auto", max_memory=mm)
    model.eval()
    run(model, "ImageTextToText (as trained)")
    import transformers.models.qwen3_5_moe.modeling_qwen3_5_moe as mq
    n_swapped = 0
    for mod in model.modules():
        if hasattr(mod, "chunk_gated_delta_rule"):
            mod.chunk_gated_delta_rule = mq.torch_chunk_gated_delta_rule
            n_swapped += 1
    print(f"swapped the fla gated-delta kernel for the torch one in {n_swapped} layers", flush=True)
    run(model, "ImageTextToText, torch gated delta")
    del model
    torch.cuda.empty_cache()
    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16, device_map="auto", max_memory=mm)
    model.eval()
    print("CausalLM class:", type(model).__name__, flush=True)
    run(model, "CausalLM")


if __name__ == "__main__":
    main()
