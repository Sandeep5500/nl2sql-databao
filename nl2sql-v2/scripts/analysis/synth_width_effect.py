"""Is synth hard because of reasoning, or because each question ANDs together
8-10 output columns?

The scorer requires EVERY gold column to match some predicted column. If synth
gold is 9 columns wide and locals are 2, synth needs 9 independent successes per
question and locals need 2 -- a difficulty difference that has nothing to do with
the reasoning we want the RSI loop to improve.

Measures: (1) gold column-count distribution, synth vs locals.
          (2) for each failed synth episode, HOW MANY gold columns went unmatched.
              Mostly-1 means near-miss compounding. Mostly-all means real failure.
"""
import csv, glob, json, os, sys, random
from collections import Counter
sys.path.insert(0, "/data/user_data/juliep2/nl2sql-databao/nl2sql-v2/src")
R = "/data/user_data/juliep2/nl2sql-databao"

def goldcols(golddir):
    out = {}
    for p in glob.glob(f"{golddir}/*.csv"):
        iid = os.path.basename(p).rsplit("_", 1)[0]
        try:
            with open(p) as f:
                h = next(csv.reader(f))
            out[iid] = len(h)
        except Exception: pass
    return out

SYN = "/data/user_data/juliep2/synthroot/Spider2/spider2-lite/evaluation_suite/gold/exec_result"
LOC = f"{R}/Spider2/spider2-lite/evaluation_suite/gold/exec_result"
sg, lg = goldcols(SYN), goldcols(LOC)

def dist(name, d, keys=None):
    vals = [v for k, v in d.items() if keys is None or k in keys]
    if not vals: print(f"{name}: none"); return
    c = Counter(vals)
    import statistics as st
    print(f"\n=== {name}: {len(vals)} questions, mean {st.mean(vals):.1f} gold columns, "
          f"median {st.median(vals):.0f} ===")
    for k in sorted(c):
        bar = "#" * int(40 * c[k] / len(vals))
        print(f"   {k:>3} cols  {c[k]:>4}  {c[k]/len(vals):>6.1%} {bar}")

# locals actually used (the 135)
loc_ids = set()
for line in open(f"{R}/Spider2/spider2-lite/spider2-lite.jsonl"):
    d = json.loads(line)
    if d["instance_id"].startswith("local"): loc_ids.add(d["instance_id"])
dist("LOCALS gold width", lg, loc_ids)
dist("SYNTH gold width", sg)

# --- accuracy by gold width, on the synth runs we have ---
def rows(pat):
    out = []
    for f in sorted(glob.glob(pat)):
        try: out.extend(csv.DictReader(open(f)))
        except Exception: pass
    return [r for r in out if r.get("instance_id")]

print("\n=== synth accuracy BY gold column count (evolve+heldout+prof, all episodes) ===")
allr = rows(f"{R}/results/synbase_*.csv") + rows(f"{R}/results/synprof_syn_*.csv")
byw = {}
for r in allr:
    w = sg.get(r["instance_id"])
    if w is None: continue
    ok = (r.get("score") or "0").strip() not in ("", "0")
    byw.setdefault(w, []).append(ok)
print(f"   {'cols':>5} {'n':>6} {'accuracy':>10}")
for w in sorted(byw):
    v = byw[w]
    if len(v) < 5: continue
    print(f"   {w:>5} {len(v):>6} {sum(v)/len(v):>9.1%}")

narrow = [ok for w, v in byw.items() if w <= 3 for ok in v]
wide   = [ok for w, v in byw.items() if w >= 7 for ok in v]
if narrow and wide:
    print(f"\n   <=3 cols : {sum(narrow)/len(narrow):.1%}  (n={len(narrow)})")
    print(f"   >=7 cols : {sum(wide)/len(wide):.1%}  (n={len(wide)})")

print("\n=== LOCALS accuracy by gold width, for comparison ===")
lrows = rows(f"{R}/results/synprof_loc_*.csv")
lbyw = {}
for r in lrows:
    w = lg.get(r["instance_id"])
    if w is None: continue
    ok = (r.get("score") or "0").strip() not in ("", "0")
    lbyw.setdefault(min(w, 7), []).append(ok)
for w in sorted(lbyw):
    v = lbyw[w]
    print(f"   {w:>5}{'+' if w==7 else ' '} {len(v):>6} {sum(v)/len(v):>9.1%}")
