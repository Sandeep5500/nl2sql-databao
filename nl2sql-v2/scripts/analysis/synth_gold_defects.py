"""How widespread are the gold defects the first gate missed?

local_syn0139 has a gold of exactly one row of EMPTY STRINGS and still counted
as clean -- preview_defect() never checked for blankness. Quantify that and the
over-specification that makes these questions unlike Spider2.
"""
import csv, glob, json, os, re, statistics as st
from collections import Counter

for NAME, ROOT in [("synthroot (147)", "/data/user_data/juliep2/synthroot"),
                   ("synthroot_full (673)", "/data/user_data/juliep2/synthroot_full")]:
    GOLD = f"{ROOT}/Spider2/spider2-lite/evaluation_suite/gold/exec_result"
    QF = f"{ROOT}/Spider2/spider2-lite/spider2-lite.jsonl"
    if not os.path.exists(QF): print(f"\n{NAME}: missing"); continue
    qs = {json.loads(l)["instance_id"]: json.loads(l) for l in open(QF)}
    defect = Counter(); widths = []; qlens = []; clauses = []
    for iid in qs:
        p = f"{GOLD}/{iid}_a.csv"
        if not os.path.exists(p): defect["gold file missing"] += 1; continue
        try:
            with open(p) as f: g = list(csv.reader(f))
        except Exception: defect["unreadable"] += 1; continue
        if len(g) < 2: defect["header only (no rows)"] += 1; continue
        hdr, body = g[0], g[1:]
        widths.append(len(hdr))
        flat = [c.strip() for r in body for c in r]
        if all(c == "" for c in flat):
            defect["ALL CELLS BLANK"] += 1; continue
        if len(body) == 1 and sum(1 for c in body[0] if c.strip() == "") >= len(hdr) / 2:
            defect["single row, half blank"] += 1; continue
        if sum(1 for c in flat if c == "") / max(len(flat), 1) > 0.5:
            defect[">50% blank cells"] += 1; continue
        q = qs[iid]["question"]
        qlens.append(len(q))
        clauses.append(len(re.findall(r"\b(then|first|next|finally|after that)\b", q, re.I)))
    n = len(qs)
    print(f"\n=== {NAME}: {n} questions ===")
    tot = sum(defect.values())
    if tot:
        print(f"  gold defects MISSED by the original gate: {tot} ({tot/n:.1%})")
        for k, v in defect.most_common(): print(f"     {v:>4}  {k}")
    else:
        print("  no blank-gold defects")
    if widths:
        print(f"  gold width: mean {st.mean(widths):.1f}, median {st.median(widths):.0f}, "
              f">=7 cols: {sum(1 for w in widths if w>=7)/len(widths):.0%}")
    if qlens:
        print(f"  question length: mean {st.mean(qlens):.0f} chars, median {st.median(qlens):.0f}")
        c = Counter(clauses)
        multi = sum(v for k, v in c.items() if k >= 1)
        print(f"  multi-step phrasing ('first/then/next/finally'): {multi}/{len(clauses)} "
              f"({multi/len(clauses):.0%})")
        print(f"  >=2 such markers: {sum(v for k,v in c.items() if k>=2)/len(clauses):.0%}")

# contrast with the real locals
R = "/data/user_data/juliep2/nl2sql-databao"
qs = [json.loads(l) for l in open(f"{R}/Spider2/spider2-lite/spider2-lite.jsonl")]
loc = [d for d in qs if d["instance_id"].startswith("local")]
ql = [len(d["question"]) for d in loc]
cl = [len(re.findall(r"\b(then|first|next|finally|after that)\b", d["question"], re.I)) for d in loc]
print(f"\n=== Spider2 LOCALS ({len(loc)}) for contrast ===")
print(f"  question length: mean {st.mean(ql):.0f} chars, median {st.median(ql):.0f}")
print(f"  multi-step phrasing: {sum(1 for c in cl if c>=1)/len(cl):.0%}")
