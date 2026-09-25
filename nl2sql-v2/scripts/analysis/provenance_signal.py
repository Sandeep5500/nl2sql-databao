#!/usr/bin/env python3
"""Does a candidate's own account of what it checked predict correctness? Backs Section 5.3.

Each pass@4 candidate's chain-of-thought was condensed into bullets that mark every
claim CHECKED (it verified this in the data) or ASSUMED (it did not). If that
provenance separated correct candidates from wrong ones it would be a feature for a
trained verifier. This scores it two ways: the literal markers, and the prose the
summariser used instead when it ignored the marker instruction.

The headline is the within-question AUC: given one correct and one wrong candidate for
the same question, how often does the score rank the correct one higher. 0.5 is chance.
Totals across questions are not the right view, because questions differ in difficulty.

Usage (from nl2sql-v2/):
    uv run python scripts/analysis/provenance_signal.py
"""

import argparse
import json
import random
import re
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]

CHECK_WORDS = re.compile(r"(?i)\b(verified|confirmed|checked|sampled|inspected|tested)\b")
ASSUME_WORDS = re.compile(r"(?i)\bassum\w*\b")
LIT_CHECK = re.compile(r"\bCHECKED\b")
LIT_ASSUME = re.compile(r"\bASSUMED\b")

MODES = {
    "literal markers": (LIT_CHECK, LIT_ASSUME),
    "prose wording": (CHECK_WORDS, ASSUME_WORDS),
}


def score(text, mode):
    c, a = MODES[mode]
    return len(c.findall(text)) - len(a.findall(text))


def auc(questions, mode):
    """P(correct candidate outranks a wrong one), ties counting half."""
    wins = pairs = 0
    for cands in questions:
        for ok_i, text_i in cands:
            for ok_j, text_j in cands:
                if ok_i and not ok_j:
                    si, sj = score(text_i, mode), score(text_j, mode)
                    pairs += 1
                    wins += 1 if si > sj else (0.5 if si == sj else 0)
    return (wins / pairs if pairs else 0.5), pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", default="validator_inputs_think.json",
                    help="candidate pool, for the recorded correctness of each candidate")
    ap.add_argument("--summaries", default="reasoning_summaries_think.json",
                    help="{instance_id: {run: summary}} produced by summarize_reasoning.py")
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()

    data = json.loads((ROOT / args.inputs).read_text())
    summaries = json.loads((ROOT / args.summaries).read_text())

    questions, flat, missing = [], [], 0
    for qid, item in data.items():
        cands = []
        for c in item["candidates"]:
            text = (summaries.get(qid) or {}).get(c["run"])
            if not text:
                missing += 1
                continue
            cands.append((bool(c["correct"]), text))
        if cands:
            questions.append(cands)
            flat.extend(cands)

    n_ok = sum(1 for ok, _ in flat if ok)
    decidable = [c for c in questions
                 if any(ok for ok, _ in c) and not all(ok for ok, _ in c)]
    print(f"{len(flat)} candidates with a summary ({missing} missing), {n_ok} correct")
    print(f"summary length: median {st.median(len(t) for _, t in flat):.0f} chars, "
          f"max {max(len(t) for _, t in flat)}")
    print(f"questions {len(questions)}, decidable (some right, some wrong) {len(decidable)}")

    print(f"\n{'signal':34s} {'correct':>9s} {'wrong':>9s}")
    for mode in MODES:
        for label, rx in zip(("checks", "assumptions"), MODES[mode]):
            per = [st.mean(len(rx.findall(t)) for ok, t in flat if ok is want)
                   for want in (True, False)]
            print(f"  {mode + ', ' + label:32s} {per[0]:9.2f} {per[1]:9.2f}")

    compliant = sum(1 for _, t in flat if LIT_CHECK.search(t) or LIT_ASSUME.search(t))
    print(f"\nsummaries using a literal marker: {compliant}/{len(flat)}"
          f"  (CHECKED {sum(1 for _, t in flat if LIT_CHECK.search(t))},"
          f" ASSUMED {sum(1 for _, t in flat if LIT_ASSUME.search(t))})")

    print(f"\n{'mode':20s} {'AUC':>6s} {'95% CI':>16s} {'pairs':>6s} {'as a selector':>14s}")
    for mode in MODES:
        point, pairs = auc(decidable, mode)
        rng = random.Random(1)
        boots = sorted(auc([rng.choice(decidable) for _ in decidable], mode)[0]
                       for _ in range(args.boot))
        lo, hi = boots[int(0.025 * args.boot)], boots[int(0.975 * args.boot) - 1]
        # argmax over the score, ties broken at random, scored over every question
        rng = random.Random(0)
        hits = 0
        for cands in questions:
            sc = [score(t, mode) for _, t in cands]
            best = [i for i, x in enumerate(sc) if x == max(sc)]
            hits += cands[rng.choice(best)][0]
        chance = sum(sum(ok for ok, _ in c) / len(c) for c in questions)
        print(f"  {mode:18s} {point:6.3f} {lo:7.3f}..{hi:<7.3f} {pairs:6d}"
              f"   {hits:3d}/{len(questions)} (chance {chance:.1f})")


if __name__ == "__main__":
    main()
