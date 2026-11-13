#!/usr/bin/env python3
"""Where do the judge-training pairs differ from the Spider2 pairs, and where did tuning help?

Both sides are read as the judge sees them (the pairwise prompt), so the same features are
measured on each:
  train    rejudge_pairs.py --verdicts outputs on the training pairs: the fresh untuned
           baseline and a tuned judge (e.g. the gate file), split trained / seen db / held out
  spider2  judge_pools.py outputs for the untuned judge (two runs) and a tuned one; every
           right-vs-wrong ordered pair, prompt rebuilt from the pools (Spider2 config)

Prints feature distributions per side, and per feature bucket: pairs, untuned accuracy,
tuned minus untuned. A bucket where tuning helps on BIRD but that Spider2 lacks (or the
reverse) says what the training data does not cover.

Usage (from nl2sql-v2/, Spider2 config):
    python scripts/analyze_judge_gap.py --verdicts verdicts_train_v1.jsonl \\
        --train-base rejudge/train_untuned.jsonl --train-tuned gate_a.jsonl --data <v2 data dir> \\
        --pools-dir results/pools --spider-base think35/qwen36-35b-think \\
        --spider-base think35_rerun/qwen36-35b-think-rerun --spider-tuned judge-tuned-v2a/judge-tuned-v2a \\
        --dump pairs_features.jsonl
"""

import argparse
import glob
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SHAPE = re.compile(r"\[(\d+) rows x (\d+) cols total\]")


def split_prompt(p):
    """question, doc, schema, (sql, result) for A and B from a PAIRWISE_PROMPT text."""
    head, _, rest = p.partition("\n--- Candidate A ---\n")
    a, _, rest = rest.partition("\n--- Candidate B ---\n")
    b = rest.split("\n\nWhich candidate correctly answers", 1)[0]
    q = head.split("Question: ", 1)[1]
    q, _, ctx = q.partition("\n")
    doc = ctx.split("\nReference documentation:\n", 1)[1] if "Reference documentation:" in ctx else ""
    doc, _, schema = doc.partition("\nSchema overview") if doc else ("", "", ctx)

    def cand(t):
        sql, _, res = t.partition("\nExecution result:\n")
        return sql.removeprefix("SQL:\n").strip(), res.strip()
    return q, doc, schema, cand(a), cand(b)


def sql_feats(sql):
    s = re.sub(r"--[^\n]*", "", sql).upper()
    return {"chars": len(sql), "ctes": len(re.findall(r"\bAS\s*\(", s)), "joins": len(re.findall(r"\bJOIN\b", s)),
            "window": bool(re.search(r"\bOVER\s*\(", s)), "subq": s.count("(SELECT")}


def shape(res):
    m = SHAPE.search(res)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def features(prompt, correct_letter):
    q, doc, schema, a, b = split_prompt(prompt)
    right, wrong = (a, b) if correct_letter == "A" else (b, a)
    (rr, rc), (wr, wc) = shape(right[1]), shape(wrong[1])
    fr, fw = sql_feats(right[0]), sql_feats(wrong[0])
    if rr is None or wr is None:
        diff = "error/no shape"
    elif rc != wc and rr != wr:
        diff = "rows+cols differ"
    elif rc != wc:
        diff = "cols differ"
    elif rr != wr:
        diff = "rows differ"
    else:
        ra = right[1].rsplit("\n[", 1)[0]
        wa = wrong[1].rsplit("\n[", 1)[0]
        diff = "same shape, same preview" if ra == wa else "same shape, values differ"
    return {
        "q_chars": len(q), "doc_chars": len(doc), "schema_chars": len(schema),
        "sql_chars_max": max(fr["chars"], fw["chars"]), "ctes_max": max(fr["ctes"], fw["ctes"]),
        "joins_max": max(fr["joins"], fw["joins"]), "window_any": fr["window"] or fw["window"],
        "right_longer_sql": fr["chars"] > fw["chars"],
        "rows_right": rr, "rows_wrong": wr, "diff": diff,
        "one_row_both": rr == 1 and wr == 1,
        "right_more_rows": None if rr is None or wr is None or rr == wr else rr > wr,
    }


def load_samples(path):
    out = defaultdict(list)
    for line in open(path):
        r = json.loads(line)
        if not r["error"] and r.get("verdict") in ("A", "B"):
            out[r["id"]].append(bool(r["right"]))
    return out


def train_side(args):
    from rejudge_pairs import from_verdicts
    base, tuned = load_samples(args.train_base), load_samples(args.train_tuned)
    trained = {json.loads(l)["pair_id"] for l in open(f"{args.data}/dpo.jsonl")}
    held = set(json.load(open(f"{args.data}/holdout.json"))["databases"])
    db = {json.loads(l)["instance_id"]: json.loads(l)["db"] for l in open(args.verdicts)}
    rows = []
    for p in from_verdicts(args.verdicts, "never,mixed,always"):
        if p["id"] not in base or p["id"] not in tuned:
            continue
        iid = p["id"].split("#")[0]
        where = "held out" if db[iid] in held else "trained" if p["id"] in trained else "seen db"
        f = features(p["prompt"], p["correct_letter"])
        f.update(side="train:" + where, id=p["id"], kind=p["kind"], source=p.get("source"),
                 base=st.mean(base[p["id"]]), tuned=st.mean(tuned[p["id"]]))
        rows.append(f)
    return rows


def spider_side(args):
    from rejudge_pairs import from_pools
    acc = {}  # (pool, iid, first, second) -> {judge: [right]}
    for name, prefix in [(f"base{i}", p) for i, p in enumerate(args.spider_base)] + [("tuned", args.spider_tuned)]:
        for f in glob.glob(f"{args.pools_dir}/{prefix}_*_n12_s*.jsonl"):
            pool = f.split("_n12_")[0].rsplit("_", 1)[1]
            for line in open(f):
                it = json.loads(line)
                for j in it["judgments"]:
                    ca = bool(it["groups"][j["first"]]["correct"])
                    if ca == bool(it["groups"][j["second"]]["correct"]) or j["p_first"] is None:
                        continue
                    key = (pool, it["instance_id"], j["first"], j["second"])
                    acc.setdefault(key, defaultdict(list))[name].append((j["p_first"] > 0.5) == ca)
    keys = [k for k, v in acc.items() if v["base0"] and v["tuned"]]
    tmp = Path(args.dump or "/tmp/_pairs").with_suffix(".spider_pairs.json")
    tmp.write_text(json.dumps([{"pool": k[0], "instance_id": k[1], "first": k[2], "second": k[3]} for k in keys]))
    prefix = args.spider_base[0]
    rows = []
    for k, p in zip(keys, from_pools(str(tmp), args.pools_dir, prefix)):
        f = features(p["prompt"], p["correct_letter"])
        b = [x for i in range(len(args.spider_base)) for x in acc[k][f"base{i}"]]
        # the first base run picks the hard pairs, the others measure them (a pair chosen
        # because a run got it wrong would otherwise look improved by any second sample)
        f.update(side="spider2", id=p["id"], kind="spider2", source="spider2", base=st.mean(b),
                 base_first=st.mean(acc[k]["base0"]),
                 base_rest=st.mean([x for i in range(1, len(args.spider_base)) for x in acc[k][f"base{i}"]] or b),
                 tuned=st.mean(acc[k]["tuned"]))
        rows.append(f)
    return rows


def bucket(name, v):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, str):
        return v
    edges = {"q_chars": [100, 200, 400], "doc_chars": [1, 200, 1000, 4000],
             "schema_chars": [2000, 5000, 10000], "sql_chars_max": [300, 600, 1200, 2500],
             "ctes_max": [1, 2, 4], "joins_max": [1, 2, 4]}[name]
    for e in edges:
        if v < e:
            return f"<{e}"
    return f">={edges[-1]}"


FEATS = ["diff", "one_row_both", "right_more_rows", "right_longer_sql", "q_chars", "doc_chars",
         "schema_chars", "sql_chars_max", "ctes_max", "joins_max", "window_any"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--train-base", required=True)
    ap.add_argument("--train-tuned", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--pools-dir", required=True)
    ap.add_argument("--spider-base", action="append", required=True)
    ap.add_argument("--spider-tuned", required=True)
    ap.add_argument("--dump")
    args = ap.parse_args()

    rows = train_side(args) + spider_side(args)
    if args.dump:
        with open(args.dump, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    # the comparison that matters: pairs the untuned judge does not always get right ("hard":
    # wrong in the first untuned run, measured by the second untuned run vs the tuned one)
    groups = {
        "train mixed (all dbs)": [r for r in rows if r["side"].startswith("train") and r["kind"] == "mixed"],
        "train held-out mixed": [r for r in rows if r["side"] == "train:held out" and r["kind"] == "mixed"],
        "train all": [r for r in rows if r["side"].startswith("train")],
        "spider2 all": [r for r in rows if r["side"] == "spider2"],
        "spider2 hard": [dict(r, base=r["base_rest"]) for r in rows
                         if r["side"] == "spider2" and r["base_first"] < 1],
    }
    print("pairs per group:", {g: len(v) for g, v in groups.items()})
    for g, v in groups.items():
        print(f"  {g:24s} untuned {st.mean(r['base'] for r in v):.1%}  tuned {st.mean(r['tuned'] for r in v):.1%}")
    for feat in FEATS:
        print(f"\n== {feat}   (share of pairs | untuned acc | tuned-untuned)")
        cells = defaultdict(lambda: defaultdict(list))
        for g, v in groups.items():
            for r in v:
                cells[bucket(feat, r[feat])][g].append(r)
        print(f"{'':26s}" + "".join(f"{g[:22]:>26s}" for g in groups))
        num = lambda b: float(re.sub(r"[^\d.]", "", b) or -1)
        for b in sorted(cells, key=lambda b: (num(b), b.startswith(">="), b)):
            line = f"{b:26s}"
            for g, v in groups.items():
                c = cells[b][g]
                if not c:
                    line += f"{'-':>26s}"
                    continue
                gain = st.mean(r["tuned"] for r in c) - st.mean(r["base"] for r in c)
                line += f"{len(c) / len(v):6.0%} n={len(c):<4d}{st.mean(r['base'] for r in c):5.0%} {gain:+5.0%} "
            print(line)
    for g in ("train mixed (all dbs)", "spider2 all"):
        v = groups[g]
        print(f"\nmedians, {g}: " + ", ".join(
            f"{k} {st.median(r[k] for r in v):.0f}" for k in ("q_chars", "doc_chars", "schema_chars", "sql_chars_max",
                                                              "ctes_max", "joins_max")))


if __name__ == "__main__":
    main()
