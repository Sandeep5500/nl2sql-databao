"""GPU-free artifact probe: can surface features of the SQL alone pick the gold?

No model, no question. If a one-line heuristic matches arm C's ~85%, then
arm C is reading syntax, not judging answers.
"""
import json, re, collections

rows = [json.loads(l) for l in open("/home/juliep2/judge/pairs.jsonl")]
held = [r for r in rows if r["split"] == "holdout"]
print("%d pairs, %d holdout\n" % (len(rows), len(held)))


def feats(sql):
    s = sql
    return {
        "chars":     len(s),
        "lines":     s.count("\n") + 1,
        "selects":   len(re.findall(r"\bSELECT\b", s, re.I)),
        "joins":     len(re.findall(r"\bJOIN\b", s, re.I)),
        "wheres":    len(re.findall(r"\bWHERE\b", s, re.I)),
        "commas":    s.count(","),
        "parens":    s.count("("),
        "ctes":      len(re.findall(r"\bWITH\b", s, re.I)),
        "aggs":      len(re.findall(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", s, re.I)),
        "groupbys":  len(re.findall(r"\bGROUP\s+BY\b", s, re.I)),
        "cases":     len(re.findall(r"\bCASE\b", s, re.I)),
        "distincts": len(re.findall(r"\bDISTINCT\b", s, re.I)),
    }


NAMES = list(feats("SELECT 1"))


def score(pairs, name):
    """accuracy of 'the SQL with the larger <name> is the gold one'; ties = coin flip"""
    win = tie = 0
    for r in pairs:
        c = feats(r["chosen"]["sql"])[name]
        j = feats(r["rejected"]["sql"])[name]
        if c > j:
            win += 1
        elif c == j:
            tie += 1
    return (win + tie / 2) / len(pairs), tie / len(pairs)


print("%-12s %12s %7s %13s" % ("feature", "holdout", "ties", "all-pairs"))
res = []
for nm in NAMES:
    a, t = score(held, nm)
    b, _ = score(rows, nm)
    res.append((abs(a - 0.5), nm, a, t, b))
for _, nm, a, t, b in sorted(res, reverse=True):
    print("%-12s %12.4f %7.2f %13.4f" % (nm, a, t, b))

best = max(res)[1]
print("\nbest single surface feature on holdout: %s" % best)

sub = [r for r in held if r["rejected"]["error_type"] != "missing_column"]
a, _ = score(sub, best)
print("  excluding missing_column (%d pairs): %.4f" % (len(sub), a))

by = collections.defaultdict(list)
for r in held:
    by[r["rejected"]["error_type"]].append(r)
for et, g in sorted(by.items()):
    a, _ = score(g, best)
    print("  %-16s %3d pairs  %.3f" % (et, len(g), a))
