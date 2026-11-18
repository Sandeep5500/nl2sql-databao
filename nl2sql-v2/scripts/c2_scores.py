#!/usr/bin/env python3
"""Scores of a two-loss judge (train_judge_lora.py choice_reason adapter), or of the untrained base, on
the held-out practice traces. For each stored reasoning sample: the log-probabilities of the two letters
at the verdict position after '<think>' reasoning '</think>' + '{"winner": "' (how a C2 judge makes its
pick), and, when the adapter has a vec_head.pt, the contrastive head's score w . h at '</think>'.

One HF forward per trace through train_judge_lora.states, so scoring reads the model exactly as training
did. forward_check runs first (for the base, the judge must also return each sample's own letter), and
every trace's hidden states are checked. Held-out traces are those of vstar_scores.py: questions on
--holdout databases or in the val split (recorded as split "heldout"). Appends to --out and skips traces
already there, so a requeued job resumes.

    python scripts/c2_scores.py --adapter <arm>/choice_reason/final --verdicts <files> \\
        --holdout holdout.json --out scores_c2_vec.jsonl
    python scripts/c2_scores.py --verdicts <files> --holdout holdout.json --out scores_base.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_judge_lora as t  # noqa: E402


def traces(verdicts, holdout):
    """The held-out traces, filtered as vstar_scores.py filters them (so the ids match)."""
    held = set(json.load(open(holdout))["databases"])
    rows = []
    for path in verdicts:
        tag = Path(path).stem.removeprefix("verdicts_")
        for line in open(path):
            r = json.loads(line)
            if not (r["split"] == "heldout" or r["db"] in held):
                continue
            for pi, p in enumerate(r["pairs"]):
                for si, s in enumerate(p["samples"]):
                    if s.get("error") or s.get("truncated") or s.get("verdict") not in ("A", "B") \
                            or not (s.get("reasoning") or "").strip() or not s.get("answer"):
                        continue
                    rows.append(dict(id=f"{tag}|{r['instance_id']}|{pi}|{si}", file=tag, instance_id=r["instance_id"],
                                     db=r["db"], split=r["split"], source=r["source"], pair=pi, first=p["first"],
                                     second=p["second"], sample=si, correct_letter=p["correct_letter"],
                                     verdict=s["verdict"], right=s["verdict"] == p["correct_letter"],
                                     prompt=p["prompt"], reasoning=s["reasoning"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", help="a choice_reason final/ dir (adapter, optional vec_head.pt); none = the base")
    ap.add_argument("--verdicts", nargs="+", required=True)
    ap.add_argument("--holdout", required=True, help="make_judge_sft_dpo.py holdout.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=t.BASE)
    ap.add_argument("--max-length", type=int, default=16384, help="longer traces are skipped")
    ap.add_argument("--experts", default="grouped_mm", choices=["grouped_mm", "eager", "batched_mm"])
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.base)
    think_end = tok.convert_tokens_to_ids("</think>")
    rows = traces(args.verdicts, args.holdout)
    out = Path(args.out)
    done = {json.loads(l)["id"] for l in open(out)} if out.exists() else set()
    todo, letter_ids, too_long = [], None, 0
    for r in rows:
        if r["id"] in done:
            continue
        _, text = t.thinking_text(tok, [{"role": "user", "content": r["prompt"]}], r["reasoning"])
        if letter_ids is None:
            letter_ids = t.letter_ids_after(tok, text)
        ids = tok(text, add_special_tokens=False).input_ids
        if len(ids) > args.max_length:
            too_long += 1
            continue
        todo.append((r, ids, len(ids) - 1 - ids[::-1].index(think_end)))
    print(f"{len(rows)} held-out traces; {len(todo)} to score ({too_long} longer than {args.max_length})", flush=True)

    from gpu_preflight import gpu_preflight
    gpu_preflight()
    gib = 2 ** 30
    mm = {i: int(torch.cuda.get_device_properties(i).total_memory * 0.92) - (4 * gib if i == 0 else 0)
          for i in range(torch.cuda.device_count())}
    model = AutoModelForImageTextToText.from_pretrained(args.base, dtype=torch.bfloat16, device_map="auto",
                                                        max_memory=mm, experts_implementation=args.experts)
    vec = None
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
        if (Path(args.adapter) / "vec_head.pt").exists():
            emb = model.get_output_embeddings().weight
            vec = torch.nn.Linear(emb.shape[1], 1, bias=False).to(emb.device, torch.float32)
            vec.load_state_dict(torch.load(Path(args.adapter) / "vec_head.pt"))
    model.eval()
    if todo:
        # the base must return each sample's own letter on this allocation; a trained adapter need not
        # (it may overrule) and may move probability off the letters, so it is checked for health only
        seqs, labels = [ids for _, ids, _ in todo], ["AB".index(r["verdict"]) for r, _, _ in todo[:8]]
        if args.adapter:
            with model.disable_adapter():
                t.forward_check(model, seqs, letter_ids, labels)
            t.forward_check(model, seqs, letter_ids, min_mass=0.0)
        else:
            t.forward_check(model, seqs, letter_ids, labels)

    dev = model.get_input_embeddings().weight.device
    with torch.no_grad(), open(out, "a") as f:
        for n, (r, ids, te) in enumerate(todo, 1):
            h, head = t.states(model, torch.tensor([ids], device=dev))
            t.assert_healthy(h, r["id"], t.STATE_LIMIT)
            logits = head(h[-1:]).float()[0]
            t.assert_healthy(logits[None], r["id"], t.LOGIT_LIMIT)
            lp = logits.log_softmax(-1)[letter_ids].tolist()
            rec = {k: v for k, v in r.items() if k not in ("prompt", "reasoning")}
            rec.update(model=args.adapter or "base", lp_a=lp[0], lp_b=lp[1], n_tokens=len(ids))
            if vec is not None:
                rec["vec"] = float(vec(h[te].to(vec.weight.device, torch.float32)))
            f.write(json.dumps(rec) + "\n")
            f.flush()
            if n % 100 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
