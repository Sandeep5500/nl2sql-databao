"""Is synth's low accuracy the AGENT being wrong, or GOLD being wrong?

Re-executes each failed episode's stored SQL and compares the real result to
gold. The discriminating signal is the SHAPE of the disagreement:

  - pred values are a SUPERSET/SUBSET of gold, or gold has a column the query
    could not have been asked for -> suspect GOLD (ambiguous/overspecified ask)
  - pred has the right shape but different numbers                -> AGENT
  - gold is 1x1 and pred is 1x1 and they differ by a clean factor  -> ambiguity

Uses nl2sql.db.Database so typeless-SQLite columns decode the same way the
harness decodes them. Bypassing it produced a wrong answer once already.
"""
import csv, glob, json, os, random, sys
from collections import Counter
sys.path.insert(0, "/data/user_data/juliep2/nl2sql-databao/nl2sql-v2/src")

ROOT = "/data/user_data/juliep2/synthroot"
R = "/data/user_data/juliep2/nl2sql-databao"
os.environ["NL2SQL_DATA_ROOT"] = ROOT

from nl2sql.db import Database

def rows(pat):
    out = []
    for f in sorted(glob.glob(pat)):
        try: out.extend(csv.DictReader(open(f)))
        except Exception: pass
    return [r for r in out if r.get("instance_id")]

qs = {}
for line in open(f"{ROOT}/Spider2/spider2-lite/spider2-lite.jsonl"):
    d = json.loads(line); qs[d["instance_id"]] = d

GOLD = f"{ROOT}/Spider2/spider2-lite/evaluation_suite/gold/exec_result"

def gold_of(iid):
    p = f"{GOLD}/{iid}_a.csv"
    if not os.path.exists(p): return None
    with open(p) as f:
        rd = list(csv.reader(f))
    return rd

def cellset(tab):
    """every value in the table, normalised -- order and layout independent"""
    out = set()
    for r in tab:
        for v in r:
            v = (str(v) or "").strip()
            try: out.add(f"{float(v):.4g}")
            except Exception:
                if v: out.add(v.lower())
    return out

fails = [r for r in rows(f"{R}/results/synprof_syn_*.csv")
         if (r.get("score") or "0").strip() in ("", "0")
         and (r.get("status") or "") == "submitted" and (r.get("sql") or "").strip()]
random.seed(7); random.shuffle(fails)
sample = fails[:60]
print(f"auditing {len(sample)} of {len(fails)} SUBMITTED synth failures\n")

tally = Counter(); examples = []
for r in sample:
    iid = r["instance_id"]; q = qs.get(iid)
    if not q: tally["question missing"] += 1; continue
    g = gold_of(iid)
    if not g or len(g) < 2: tally["gold missing"] += 1; continue
    gh, gb = g[0], g[1:]
    sql = (r["sql"] or "").replace("\\n", "\n")
    try:
        db = Database(f"{ROOT}/Spider2/spider2-lite/resource/databases/spider2-localdb/{q['db']}.sqlite")
        df = db.query(sql, max_rows=100000)
        pb = df.values.tolist(); ph = list(df.columns)
    except Exception as e:
        tally[f"pred re-exec error: {type(e).__name__}"] += 1
        if tally[f"pred re-exec error: {type(e).__name__}"] <= 2:
            print(f"   [exec err] {iid}: {type(e).__name__}: {str(e)[:160]}")
        continue

    gs, ps = cellset(gb), cellset(pb)
    inter = gs & ps
    if not gs: tally["gold empty"] += 1; continue
    cov_g = len(inter) / len(gs)
    cov_p = len(inter) / max(len(ps), 1)

    if cov_g >= 0.99 and cov_p >= 0.99:
        k = "SAME VALUES, different layout -> SCORER/shape"
    elif cov_g >= 0.99:
        k = "pred SUPERSET of gold -> pred answered more (gold narrower)"
    elif cov_p >= 0.99:
        k = "pred SUBSET of gold -> pred answered less"
    elif cov_g >= 0.5:
        k = "majority of gold values present -> partial"
    elif cov_g == 0:
        k = "NO overlap -> genuinely different answer"
    else:
        k = "small overlap -> genuinely different answer"
    tally[k] += 1
    if len(examples) < 8 and cov_g > 0.5:
        examples.append((iid, q["question"][:110], gh, len(gb), ph, len(pb), round(cov_g,2)))

print("=== disagreement shape, submitted synth failures ===")
for k, v in tally.most_common():
    print(f"   {v:>4}  {v/len(sample):>6.1%}  {k}")

print("\n=== examples where gold values DO appear in the prediction ===")
for iid, qq, gh, gn, ph, pn, cov in examples:
    print(f"\n  {iid}  cov_gold={cov}")
    print(f"    Q    : {qq}")
    print(f"    gold : {gn} rows, cols={gh}")
    print(f"    pred : {pn} rows, cols={ph}")
