"""Where two candidate results differ, as text for the judge (judge_prompts "diff_cmp"): shapes,
column pairs, a key match of rows, and the cells that differ. It says where the results differ,
never which is right. Numbers within 0.01 count as equal and NULL equals NULL, as in the
scorer (nl2sql.eval._vectors_match); the text is capped at 2,500 characters.

    compare_results(df_a, df_b, rows_a=None, rows_b=None, capped=False) -> str
"""

import math
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nl2sql.eval import _normalize, _vectors_match  # noqa: E402

CAP = 2500
LIST = 10


def _val(x):
    x = _normalize(x)
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _same(a, b):
    a, b = _val(a), _val(b)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), abs_tol=1e-2)
    return a == b


def _show(x):
    x = _val(x)
    if x is None:
        return "NULL"
    s = f"{x:.6g}" if isinstance(x, float) else str(x)
    return s if len(s) <= 40 else s[:37] + "..."


def _bucket(x):
    """Hashable stand-in for counting values: numbers rounded to 2 decimals."""
    x = _val(x)
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return ("n", round(float(x), 2))
    return ("s", x)


def _multiset_diff(va, vb):
    """Values only in A and only in B (order ignored), numbers within 0.01 matched."""
    ca, cb = Counter(map(_bucket, va)), Counter(map(_bucket, vb))
    only_a = list((ca - cb).elements())
    only_b = list((cb - ca).elements())
    # second pass: numbers that rounded apart but are within the tolerance
    rest_b = list(only_b)
    keep_a = []
    for x in only_a:
        for i, y in enumerate(rest_b):
            if x[0] == y[0] == "n" and abs(x[1] - y[1]) <= 1e-2 + 1e-9:
                rest_b.pop(i)
                break
        else:
            keep_a.append(x)
    show = lambda b: "NULL" if b[1] is None else (f"{b[1]:.6g}" if b[0] == "n" else _show(b[1]))
    return [show(x) for x in keep_a], [show(y) for y in rest_b]


def _fmt_list(items):
    items = list(items)
    s = ", ".join(items[:LIST])
    return s + (", …" if len(items) > LIST else "")


def _kind(col):
    """'n' for a numeric column, 's' otherwise (used to keep pairs type-compatible)."""
    vals = [_val(x) for x in col if _val(x) is not None]
    return "n" if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) else "s"


def _tokens(name):
    import re
    return {t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if len(t) >= 3}


def _pair_columns(a, b):
    """Pairs (i, j) by: the same name; the same values (order ignored); mostly shared values
    (Jaccard >= 0.5 of distinct values); a shared name token. Pairs of a numeric and a text
    column are never made by the last two. Nothing is paired by position alone."""
    pairs, used_a, used_b = [], set(), set()
    lower_b = {}
    for j, c in enumerate(b.columns):
        lower_b.setdefault(str(c).strip().lower(), j)
    for i, c in enumerate(a.columns):
        j = lower_b.get(str(c).strip().lower())
        if j is not None and j not in used_b:
            pairs.append((i, j)); used_a.add(i); used_b.add(j)
    if a.shape[0] == b.shape[0]:
        for i in range(a.shape[1]):
            if i in used_a:
                continue
            for j in range(b.shape[1]):
                if j not in used_b and _vectors_match(a.iloc[:, i].tolist(), b.iloc[:, j].tolist(), ignore_order=True):
                    pairs.append((i, j)); used_a.add(i); used_b.add(j)
                    break
    kinds_a = {i: _kind(a.iloc[:, i]) for i in range(a.shape[1]) if i not in used_a}
    kinds_b = {j: _kind(b.iloc[:, j]) for j in range(b.shape[1]) if j not in used_b}
    sets_a = {i: set(map(_bucket, a.iloc[:, i])) for i in kinds_a}
    sets_b = {j: set(map(_bucket, b.iloc[:, j])) for j in kinds_b}
    cand = []
    for i in kinds_a:
        for j in kinds_b:
            if kinds_a[i] != kinds_b[j]:
                continue
            inter = len(sets_a[i] & sets_b[j])
            jac = inter / max(1, len(sets_a[i] | sets_b[j]))
            tok = len(_tokens(a.columns[i]) & _tokens(b.columns[j]))
            close = 0.0  # single numeric rows: nearer values pair first
            if a.shape[0] == b.shape[0] == 1 and kinds_a[i] == "n":
                va, vb = _val(a.iat[0, i]), _val(b.iat[0, j])
                close = -abs(float(va) - float(vb)) if va is not None and vb is not None else float("-inf")
            if jac >= 0.5 or tok:
                cand.append((jac >= 0.5, tok, jac, close, -i, -j, i, j))
    for *_, i, j in sorted(cand, reverse=True):
        if i not in used_a and j not in used_b:
            pairs.append((i, j)); used_a.add(i); used_b.add(j)
    pairs.sort()
    return pairs, [i for i in range(a.shape[1]) if i not in used_a], [j for j in range(b.shape[1]) if j not in used_b]


def _unique(df, cols):
    keys = [tuple(_bucket(x) for x in row) for row in df.iloc[:, cols].itertuples(index=False)]
    return len(keys) == len(set(keys))


def _dup_columns(df, label):
    out = []
    for i in range(df.shape[1]):
        for j in range(i + 1, df.shape[1]):
            if df.shape[0] and all(_same(x, y) for x, y in zip(df.iloc[:, i], df.iloc[:, j])):
                out.append(f"Within {label}: {df.columns[i]} equals {df.columns[j]} in all {df.shape[0]} rows.")
    return out[:3]


def compare_results(a, b, rows_a=None, rows_b=None, capped=False):
    rows_a = a.shape[0] if rows_a is None else rows_a
    rows_b = b.shape[0] if rows_b is None else rows_b
    lines = [f"Shapes: A {rows_a} rows x {a.shape[1]} cols; B {rows_b} rows x {b.shape[1]} cols."
             + (" (compared on the first 50 rows)" if capped else "")]
    pairs, only_a, only_b = _pair_columns(a, b)
    if pairs:
        lines.append("Column pairs: " + "; ".join(f"A.{a.columns[i]} ~ B.{b.columns[j]}" for i, j in pairs) + ".")
    if only_a:
        lines.append("Only in A: " + ", ".join(map(str, a.columns[only_a])) + ".")
    if only_b:
        lines.append("Only in B: " + ", ".join(map(str, b.columns[only_b])) + ".")
    if a.shape[0] == 0 or b.shape[0] == 0:
        lines.append(("A is empty. " if a.shape[0] == 0 else "") + ("B is empty." if b.shape[0] == 0 else ""))
    elif a.shape[0] == 1 and b.shape[0] == 1:
        diff = [f"{a.columns[i]}: {_show(a.iat[0, i])} | {_show(b.iat[0, j])}" for i, j in pairs
                if not _same(a.iat[0, i], b.iat[0, j])]
        same = [str(a.columns[i]) for i, j in pairs if _same(a.iat[0, i], b.iat[0, j])]
        if pairs:
            lines.append("Single rows: " + ("differs in " + "; ".join(diff) if diff else "no paired value differs")
                         + (f"; same in {', '.join(same)}" if same and diff else "") + ".")
        if only_a or only_b:
            lines.append("Unpaired values: " + "; ".join(
                [f"A.{a.columns[i]}={_show(a.iat[0, i])}" for i in only_a] +
                [f"B.{b.columns[j]}={_show(b.iat[0, j])}" for j in only_b]) + ".")
    elif not pairs:
        lines.append("No columns could be paired.")
    else:
        # key: a column (text columns first) unique on both sides, else the first unique two-column combination
        order = sorted(pairs, key=lambda p: (_kind(a.iloc[:, p[0]]) != "s", p))
        key = next(([p] for p in order if _unique(a, [p[0]]) and _unique(b, [p[1]])), None)
        if key is None:
            from itertools import combinations
            key = next((list(c) for c in combinations(order, 2)
                        if _unique(a, [p[0] for p in c]) and _unique(b, [p[1] for p in c])), None)
        if key:
            ka = {tuple(_bucket(x) for x in r): n for n, r in enumerate(a.iloc[:, [p[0] for p in key]].itertuples(index=False))}
            kb = {tuple(_bucket(x) for x in r): n for n, r in enumerate(b.iloc[:, [p[1] for p in key]].itertuples(index=False))}
            shared = [k for k in ka if k in kb]
            one = lambda v: "NULL" if v[1] is None else (f"{v[1]:.6g}" if v[0] == "n" else _show(v[1]))
            show_key = lambda k: one(k[0]) if len(k) == 1 else "(" + ", ".join(one(v) for v in k) + ")"
            name = "+".join(str(a.columns[p[0]]) for p in key)
            lines.append(f"Key {name}: {len(shared)} in both; only in A ({len(ka) - len(shared)}): "
                         f"{_fmt_list(show_key(k) for k in ka if k not in kb) or '-'}; only in B ({len(kb) - len(shared)}): "
                         f"{_fmt_list(show_key(k) for k in kb if k not in ka) or '-'}.")
            for i, j in pairs:
                if (i, j) in key:
                    continue
                d = [k for k in shared if not _same(a.iat[ka[k], i], b.iat[kb[k], j])]
                if d:
                    lines.append(f"{a.columns[i]}: differs in {len(d)} of {len(shared)} shared keys: "
                                 + _fmt_list(f"{show_key(k)} {_show(a.iat[ka[k], i])} | {_show(b.iat[kb[k], j])}" for k in d) + ".")
                elif shared:
                    lines.append(f"{a.columns[i]}: same in all {len(shared)} shared keys.")
        else:
            for i, j in pairs:
                oa, ob = _multiset_diff(a.iloc[:, i].tolist(), b.iloc[:, j].tolist())
                if not oa and not ob:
                    lines.append(f"{a.columns[i]}: same values (order ignored).")
                else:
                    lines.append(f"{a.columns[i]}: only in A ({len(oa)}): {_fmt_list(oa) or '-'}; "
                                 f"only in B ({len(ob)}): {_fmt_list(ob) or '-'}.")
    lines += _dup_columns(a, "A") + _dup_columns(b, "B")
    text = "\n".join(lines)
    return text if len(text) <= CAP else text[:CAP - 1] + "…"


if __name__ == "__main__":  # tiny self-check
    A = pd.DataFrame({"director": ["Mangold", "Russo A", "Russo J", "Elliott"], "movie_count": [2, 2, 2, 2]})
    B = pd.DataFrame({"director": ["Mangold", "Russo A", "Russo J", "Shahir"], "movie_count": [4, 3, 3, 3]})
    print(compare_results(A, B))
    print(compare_results(pd.DataFrame({"x": [4.82], "n": [18653]}), pd.DataFrame({"avg": [4.92]})))
