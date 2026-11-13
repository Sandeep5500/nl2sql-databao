#!/usr/bin/env python3
"""Turn sampled judge verdicts (sample_judge_verdicts.py) into SFT and DPO files for
the judge adapter.

A sample is usable when its verdict parsed and the token limit did not cut it off.
Per ordered pair (one prompt):
  SFT  up to --sft-per-pair samples that picked the correct answer
  DPO  up to --dpo-per-pair (right, wrong) sample pairs on that prompt
  choice  the prompt and its correct letter, no sample needed (choice.jsonl, for the
       verdict-only stage of train_judge_lora.py); same pairs and repeats as the other two
A pair the judge never gets right goes to hard_pairs.jsonl (resample it, or drop
it); one it always gets right gives SFT examples only. Only questions whose database
is in the train split are used. Pools with a lone correct lane among several answers,
the case round-robin most often loses, are repeated --lone-weight times. At most
--max-pairs-per-question unordered pairs (both orders each) come from one question.

--extra-samples adds later samples of the same pairs (rejudge_pairs.py --verdicts outputs,
ids <instance_id>#<pair index>). --rationales adds STaR-style samples (rationalize_pairs.py:
the judge told the answer and asked to reason to it, kept only when the reasoning does not
lean on being told); they serve as the chosen side for pairs with no right sample of
their own. --holdout-frac keeps that share of the training databases out of both files
(listed in holdout.json), to check the trained judge on databases it never saw;
--holdout-file reuses an earlier build's holdout.json instead, so two trainings are checked
on the same databases. --drop-pairs drops the pairs check_pair_labels.py labelled
other_reading (the "wrong" side follows a reading the question allows). --source-weight
repeats one source's rows, e.g. complex=2.

Output (--out-dir): sft.jsonl and dpo.jsonl in TRL's conversational format (the
assistant turn carries the reasoning as reasoning_content, which Qwen's chat template
renders as the <think> block), hard_pairs.jsonl, holdout.json and stats.json.

Usage: uv run python scripts/make_judge_sft_dpo.py \\
           --verdicts '../results/judge_train/verdicts_*.jsonl' --out-dir ../results/judge_train/data
"""

import argparse
import glob
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def assistant(s: dict) -> dict:
    return {"role": "assistant", "content": s["answer"], "reasoning_content": s["reasoning"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True, help="comma-separated files or globs")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sft-per-pair", type=int, default=2)
    ap.add_argument("--dpo-per-pair", type=int, default=2)
    ap.add_argument("--lone-weight", type=int, default=2)
    ap.add_argument("--max-pairs-per-question", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--extra-samples", default="", help="comma-separated rejudge_pairs.py outputs")
    ap.add_argument("--rationales", default="", help="comma-separated rationalize_pairs.py outputs")
    ap.add_argument("--holdout-frac", type=float, default=0.0)
    ap.add_argument("--holdout-seed", type=int, default=0)
    ap.add_argument("--holdout-file", help="holdout.json of an earlier build (overrides --holdout-frac)")
    ap.add_argument("--drop-pairs", default="", help="comma-separated check_pair_labels.py outputs")
    ap.add_argument("--source-weight", default="", help="comma-separated source=repeats, e.g. complex=2")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    files = sorted({f for pat in args.verdicts.split(",") for f in glob.glob(pat)})
    if not files:
        raise SystemExit(f"no verdict files match {args.verdicts}")

    def by_id(paths):
        out = defaultdict(list)
        for path in filter(None, paths.split(",")):
            for r in map(json.loads, open(path)):
                if not r.get("error"):
                    out[r["id"]].append(r)
        return out
    extra, rationales = by_id(args.extra_samples), by_id(args.rationales)
    records = [rec for path in files for rec in map(json.loads, open(path))]
    dbs = sorted({rec["db"] for rec in records if rec.get("split") == "train"})
    if args.holdout_file:
        held = set(json.load(open(args.holdout_file))["databases"])
    else:
        held = set(random.Random(args.holdout_seed).sample(dbs, round(len(dbs) * args.holdout_frac)))
    dropped = {r["id"] for path in filter(None, args.drop_pairs.split(","))
               for r in map(json.loads, open(path)) if r["label"] == "other_reading"}
    source_weight = {k: int(v) for k, _, v in (s.partition("=") for s in filter(None, args.source_weight.split(",")))}

    sft, dpo, hard, choice, stats = [], [], [], [], Counter()
    for rec in records:
        if rec.get("split") != "train":
            stats["questions_not_train"] += 1
            continue
        if rec["db"] in held:
            stats["questions_held_out"] += 1
            continue
        if not rec["pairs"]:
            stats["questions_without_pairs"] += 1
            continue
        stats["questions_used"] += 1
        correct_lanes = sum(len(g["lanes"]) for g in rec["groups"] if g["correct"])
        lone = correct_lanes == 1 and sum(len(g["lanes"]) for g in rec["groups"]) >= 2
        weight = (args.lone_weight if lone else 1) * source_weight.get(rec.get("source"), 1)
        stats["lone_correct_questions"] += lone
        by_pair = defaultdict(list)  # both orders of one unordered pair stay together
        for p in rec["pairs"]:
            by_pair[frozenset((p["first"], p["second"]))].append(p)
        keys = list(by_pair)
        rng.shuffle(keys)
        index = {id(p): pi for pi, p in enumerate(rec["pairs"])}
        # check_pair_labels.py ids one order of the pair: drop both
        drop = {k for k in keys if any(f"{rec['instance_id']}#{index[id(p)]}" in dropped for p in by_pair[k])}
        stats["pairs_dropped_other_reading"] += len(drop)
        keys = [k for k in keys if k not in drop]
        for key in keys[:args.max_pairs_per_question]:
            for p in by_pair[key]:
                pid = f"{rec['instance_id']}#{index[id(p)]}"
                usable = [s for s in p["samples"] + extra[pid]
                          if s["verdict"] and not s["truncated"] and not s.get("error")]
                right = [s for s in usable if s["right"]]
                if not right:  # STaR: reasoning the judge reached when told the answer
                    right = [s for s in rationales[pid] if s["right"] and not s["truncated"]]
                    stats["pairs_rationalized"] += bool(right)
                wrong = [s for s in usable if not s["right"]]
                stats["ordered_pairs"] += 1
                stats["samples_usable"] += len(usable)
                stats["samples_right"] += len(right)
                meta = {"instance_id": rec["instance_id"], "pair_id": pid, "source": rec.get("source"),
                        "first": p["first"], "second": p["second"],
                        "correct_letter": p["correct_letter"], "lone_correct": lone}
                choice += [{"prompt": [{"role": "user", "content": p["prompt"]}], **meta}] * weight
                if not right:
                    stats["pairs_never_right"] += 1
                    hard.append({**meta, "n_usable": len(usable), "prompt": p["prompt"]})
                    continue
                if not wrong:
                    stats["pairs_always_right"] += 1
                user = [{"role": "user", "content": p["prompt"]}]
                for s in rng.sample(right, min(len(right), args.sft_per_pair)):
                    sft += [{"messages": user + [assistant(s)], **meta}] * weight
                for r, w in list(zip(rng.sample(right, len(right)),
                                     rng.sample(wrong, len(wrong))))[:args.dpo_per_pair]:
                    dpo += [{"prompt": user, "chosen": [assistant(r)],
                             "rejected": [assistant(w)], **meta}] * weight

    rng.shuffle(sft)
    rng.shuffle(dpo)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sft", sft), ("dpo", dpo), ("hard_pairs", hard)):
        with open(out / f"{name}.jsonl", "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    holdout = ({**json.load(open(args.holdout_file)), "from": args.holdout_file} if args.holdout_file else
               {"databases": sorted(held), "seed": args.holdout_seed, "frac": args.holdout_frac})
    (out / "holdout.json").write_text(json.dumps(holdout, indent=1) + "\n")
    stats.update({"sft_examples": len(sft), "dpo_examples": len(dpo),
                  "sft_correct_A": sum(r["correct_letter"] == "A" for r in sft),
                  "dpo_correct_A": sum(r["correct_letter"] == "A" for r in dpo)})
    stats.update({f"sft_from_{k}": v for k, v in Counter(r["source"] for r in sft).items()})
    (out / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats, indent=1))
    # the choice file is shuffled with its own generator, so sft/dpo stay as before
    random.Random(args.seed).shuffle(choice)
    with open(out / "choice.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in choice)
    cstats = {"choice_examples": len(choice), "choice_pairs": len({r["pair_id"] for r in choice}),
              "choice_correct_A": sum(r["correct_letter"] == "A" for r in choice),
              **{f"choice_from_{k}": v for k, v in Counter(r["source"] for r in choice).items()}}
    (out / "choice_stats.json").write_text(json.dumps(cstats, indent=1) + "\n")
    print(json.dumps(cstats, indent=1))


if __name__ == "__main__":
    main()
