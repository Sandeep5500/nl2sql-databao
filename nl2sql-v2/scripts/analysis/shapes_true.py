"""Row-shape analysis using the TRUE row count of the submitted result.

The tool result for a truncated preview ends with '[showing N of M rows]'; M is the real
row count. An untruncated result's row count is its number of data lines.
"""
import csv, json, re, collections
from pathlib import Path
ROOT = Path(r"C:\Users\rohin\Documents\CMU\Capstone\nl2sql-databao")
GOLD = ROOT / "Spider2/spider2-lite/evaluation_suite/gold/exec_result"
LANES = {"bq_v3": ("logs/traces/bq_v3", "results/bq_v3_run.csv"),
         "bq_v3r": ("logs/traces/bq_v3r", "results/bq_v3r_run.csv"),
         "C": ("results/full_C/traces", "results/full_C/all.csv"),
         "T": ("results/full_T/traces", "results/full_T/all.csv"),
         "C2": ("results/full_C2/traces", "results/full_C2/all.csv"),
         "R": ("results/full_R/traces", "results/full_R/all.csv")}
_gold = {}
def gold_rows(i):
    if i not in _gold:
        ns = []
        for p in sorted(GOLD.glob(f"{i}_*.csv")) or sorted(GOLD.glob(f"{i}.csv")):
            with open(p, newline="", encoding="utf-8") as f:
                ns.append(sum(1 for _ in csv.reader(f)) - 1)
        _gold[i] = ns
    return _gold[i]

_rub = {}
def rubric_exact(i):
    if i not in _rub:
        p = ROOT / "results/full_C/rubrics" / f"{i}.json"
        rb = (json.loads(p.read_text(encoding="utf-8")).get("rubric") or {}) if p.exists() else {}
        _rub[i] = rb.get("exact_rows") if (rb.get("rows_confidence") == "high") else None
    return _rub[i]

def submitted_true_rows(t):
    tr = t.get("trace", [])
    qid = None
    for s in tr:
        a = s.get("assistant")
        if a and "submit_result" in str(a):
            m = re.search(r'query_id\\*"?\s*:\s*\\*"(q\d+)', str(a))
            if m: qid = m.group(1)
    if qid is None: return None
    for s in tr:
        r = str(s.get("result", ""))
        if r.startswith(f"query_id='{qid}'"):
            m = re.search(r"\[showing \d+ of (\d+) rows\]", r)
            if m: return int(m.group(1))
            body = r.split("\n", 1)[1].split("\n\n[")[0] if "\n" in r else ""
            lines = [l for l in body.replace("\r", "").split("\n") if l.strip()]
            return max(0, len(lines) - 1)
    return None

def kind(n, g, status):
    if status == "fallback": return "ran out of steps"
    if n is None: return "no submission"
    if not g: return "unknown"
    if n in g: return "right row count"
    return "too many rows" if n > max(g) else "too few rows"

def lane_kinds(lane):
    td, cp = LANES[lane]
    R = {r["instance_id"]: r for r in csv.DictReader(open(ROOT / cp, newline="", encoding="utf-8"))}
    cat = collections.Counter(); extra = collections.Counter()
    per = {}
    for i, r in R.items():
        p = ROOT / td / f"{i}.json"
        if not p.exists(): continue
        t = json.loads(p.read_text(encoding="utf-8"))
        n = submitted_true_rows(t); g = gold_rows(i)
        per[i] = (n, g, t.get("status"))
        if r["score"] == "1":
            ex = rubric_exact(i)
            if ex is not None and n is not None and n != ex: extra["correct but rows != rubric count"] += 1
            continue
        k = kind(n, g, t.get("status")); cat[k] += 1
        ex = rubric_exact(i)
        if k == "too many rows" and ex is not None and ex in g: extra["too many, rubric count right"] += 1
        if k == "too many rows" and ex is None: extra["too many, no confident rubric"] += 1
    return cat, extra, per

if __name__ == "__main__":
    res = {l: lane_kinds(l) for l in LANES}
    keys = ["right row count", "too many rows", "too few rows", "ran out of steps", "no submission", "unknown"]
    print(f"{'wrong episodes by TRUE row shape':40s}" + "".join(f"{l:>8s}" for l in LANES))
    for k in keys: print(f"{k:40s}" + "".join(f"{res[l][0][k]:8d}" for l in LANES))
    for k in ("too many, rubric count right", "too many, no confident rubric", "correct but rows != rubric count"):
        print(f"{k:40s}" + "".join(f"{res[l][1][k]:8d}" for l in LANES))
