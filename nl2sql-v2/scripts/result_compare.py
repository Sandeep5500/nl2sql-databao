"""Where two candidate results differ, as text for the judge (judge_prompts "diff_cmp"): shapes,
column pairs, a key match of rows, and the cells that differ. It says where the results differ,
never which is right. Numbers within 0.01 count as equal and NULL equals NULL, as in the
scorer (nl2sql.eval._vectors_match); the text is capped at 2,500 characters.

A side whose true row count (rows_a, rows_b) is larger than its frame is a preview of its first
rows (BigQuery, read from the agent's trace; the agent's tool shows a varying number of rows). A row
or value missing from a preview may be among its hidden rows, so only what the other, complete side
lacks is listed. capped is implied by the row counts and kept for callers.

version=3 (BigQuery ablation, Nov 18; the default 2 is the text the judges were evaluated with) adds:
row keys written differently on the two sides matched by their words ("Brazil" ~ "Federative Republic
of Brazil"); unpaired number columns that agree on the matched rows, also at x100 / x1000 scale or with
the sign flipped; enough digits to tell two differing numbers apart; a note instead of a row match when
one side looks like the other in long form; no "equals" lines for empty columns; plural column-name words.

    compare_results(df_a, df_b, rows_a=None, rows_b=None, capped=False, version=2) -> str
"""

import math
import numbers
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nl2sql.eval import _normalize, _vectors_match  # noqa: E402

CAP = 2500
LIST = 10


def _val(x):
    x = _normalize(x)
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _real(x):
    return isinstance(x, numbers.Real) and not isinstance(x, bool)


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


def _show_pair(x, y):
    """Both values as _show prints them, with more digits when that prints two different numbers alike."""
    sx, sy = _show(x), _show(y)
    vx, vy = _val(x), _val(y)
    if sx == sy and _real(vx) and _real(vy) and vx != vy:
        for p in range(7, 16):
            sx, sy = f"{float(vx):.{p}g}", f"{float(vy):.{p}g}"
            if sx != sy:
                break
    return sx, sy


def _bucket(x):
    """Hashable stand-in for counting values: numbers rounded to 2 decimals; integers too large for a
    float to hold exactly (BigQuery IDs) are kept whole."""
    x = _val(x)
    if isinstance(x, numbers.Integral) and not isinstance(x, bool) and abs(x) >= 2 ** 53:
        return ("n", int(x))
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return ("n", round(float(x), 2))
    return ("s", x)


def _num(v):
    """A bucketed number as text: whole integers exactly, other numbers to 6 significant digits."""
    return str(v) if isinstance(v, int) else f"{v:.6g}"


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
    show = lambda b: "NULL" if b[1] is None else (_num(b[1]) if b[0] == "n" else _show(b[1]))
    return [show(x) for x in keep_a], [show(y) for y in rest_b]


def _fmt_list(items):
    items = list(items)
    s = ", ".join(items[:LIST])
    return s + (", …" if len(items) > LIST else "")


def _kind(col):
    """'n' for a numeric column, 's' otherwise (used to keep pairs type-compatible)."""
    vals = [_val(x) for x in col if _val(x) is not None]
    return "n" if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) else "s"


def _tokens(name, plural=False):
    toks = {t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if len(t) >= 3}
    return {t[:-1] if plural and len(t) > 3 and t.endswith("s") else t for t in toks}


_STOP = {"of", "the", "and", "or", "a", "an"}


def _words(x):
    return frozenset(t for t in re.split(r"[^a-z0-9]+", str(x).casefold()) if t and t not in _STOP)


def _match_by_words(keys_a, keys_b):
    """{A key: B key} for single text keys whose word sets are equal or one holds the other, one to one."""
    wa = {k: _words(k[0][1]) for k in keys_a if k[0][0] == "s" and k[0][1] is not None}
    wb = {k: _words(k[0][1]) for k in keys_b if k[0][0] == "s" and k[0][1] is not None}
    fwd, back = defaultdict(list), defaultdict(list)
    for x, sx in wa.items():
        for y, sy in wb.items():
            if sx and sy and (sx <= sy or sy <= sx):
                fwd[x].append(y)
                back[y].append(x)
    return {x: ys[0] for x, ys in fwd.items() if len(ys) == 1 and len(back[ys[0]]) == 1}


_SCALES = [(1, False, ""), (-1, False, " with the sign flipped"), (100, False, " x 100"), (-100, False, " x -100"),
           (0.01, False, " / 100"), (-0.01, False, " / -100"), (1000, False, " x 1000"), (0.001, False, " / 1000"),
           (1, True, " in absolute value"), (100, True, " in absolute value x 100"), (0.01, True, " in absolute value / 100")]


def _scaled_agreement(xs, ys):
    """The first relation y = s * x (or s * |x|, |y| = s * |x|) within 0.01 on at least 80% of at least
    2 value pairs, as text, else None."""
    pts = [(float(x), float(y)) for x, y in zip(map(_val, xs), map(_val, ys)) if _real(x) and _real(y)]
    if len(pts) < 2:
        return None
    for s, absolute, label in _SCALES:
        f = (lambda x, y: abs(s * abs(x) - abs(y))) if absolute else (lambda x, y: abs(s * x - y))
        if sum(f(x, y) <= 1e-2 + 1e-9 * abs(y) for x, y in pts) >= 0.8 * len(pts):
            return label
    return None


def _empty(x):
    """NULL, NaN or blank before normalization (which turns NaN and 'nan' into 0)."""
    return x is None or (isinstance(x, float) and math.isnan(x)) or \
        (isinstance(x, str) and x.strip().lower() in ("", "nan", "none", "null"))


def _layout_note(a, b, rows_a, rows_b):
    """A note when one side has k times the other's rows, at most 4 columns and a text column with up to
    k values, and the other side has more than k columns: the long form of the same values."""
    for w, rw, l, rl, wn, ln in ((a, rows_a, b, rows_b, "A", "B"), (b, rows_b, a, rows_a, "B", "A")):
        if rw and rl % rw == 0 and 2 <= rl // rw <= 30 and l.shape[1] <= 4 and w.shape[1] > rl // rw:
            k = rl // rw
            for c in l.columns:
                n = l[c].nunique(dropna=True)
                if _kind(l[c]) == "s" and 2 <= n <= k and (n == k or l.shape[0] < rl):
                    return (f"{ln} has {k} times as many rows as {wn}, and its column {c} has {k if n == k else 'up to ' + str(k)} "
                            f"values: {ln} may give {wn}'s values in long form, one row per {c}. Rows are not matched one to one.")
    return None


def _pair_columns(a, b, version=2):
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
            tok = len(_tokens(a.columns[i], version >= 3) & _tokens(b.columns[j], version >= 3))
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


def _dup_columns(df, label, partial=False, version=2):
    out = []
    for i in range(df.shape[1]):
        for j in range(i + 1, df.shape[1]):
            if version >= 3 and all(_empty(x) for x in df.iloc[:, i]):
                continue
            if df.shape[0] and all(_same(x, y) for x, y in zip(df.iloc[:, i], df.iloc[:, j])):
                out.append(f"Within {label}: {df.columns[i]} equals {df.columns[j]} in all {df.shape[0]} rows"
                           + (" shown." if partial else "."))
    return out[:3]


def compare_results(a, b, rows_a=None, rows_b=None, capped=False, version=2):
    rows_a = a.shape[0] if rows_a is None else rows_a
    rows_b = b.shape[0] if rows_b is None else rows_b
    part_a, part_b = rows_a > a.shape[0], rows_b > b.shape[0]  # previews (module docstring)
    lines = [f"Shapes: A {rows_a} rows x {a.shape[1]} cols; B {rows_b} rows x {b.shape[1]} cols."
             + (f" Only some rows were shown: A {a.shape[0]} of {rows_a}, B {b.shape[0]} of {rows_b}; "
                "rows not shown are not compared." if part_a or part_b else "")]
    pairs, only_a, only_b = _pair_columns(a, b, version)
    if pairs:
        lines.append("Column pairs: " + "; ".join(f"A.{a.columns[i]} ~ B.{b.columns[j]}" for i, j in pairs) + ".")
    if only_a:
        lines.append("Only in A: " + ", ".join(map(str, a.columns[only_a])) + ".")
    if only_b:
        lines.append("Only in B: " + ", ".join(map(str, b.columns[only_b])) + ".")
    if a.shape[0] == 0 or b.shape[0] == 0:
        lines.append(("A is empty. " if a.shape[0] == 0 else "") + ("B is empty." if b.shape[0] == 0 else ""))
    elif a.shape[0] == 1 and b.shape[0] == 1 and not (part_a or part_b):
        shown = (lambda x, y: " | ".join(_show_pair(x, y))) if version >= 3 else (lambda x, y: f"{_show(x)} | {_show(y)}")
        diff = [f"{a.columns[i]}: {shown(a.iat[0, i], b.iat[0, j])}" for i, j in pairs
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
    elif version >= 3 and _layout_note(a, b, rows_a, rows_b):
        lines.append(_layout_note(a, b, rows_a, rows_b))
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
            one = lambda v: "NULL" if v[1] is None else (_num(v[1]) if v[0] == "n" else _show(v[1]))
            show_key = lambda k: one(k[0]) if len(k) == 1 else "(" + ", ".join(one(v) for v in k) + ")"
            name = "+".join(str(a.columns[p[0]]) for p in key)
            match = {}  # A key -> B key written differently (version 3)
            if version >= 3 and len(key) == 1 and len(shared) < min(len(ka), len(kb)):
                match = _match_by_words([k for k in ka if k not in kb], [k for k in kb if k not in ka])
            kb_of = {k: k for k in shared}
            kb_of.update(match)
            matched_b = set(match.values())
            # a key one side shows is missing from the other only if the other shows all its rows
            only_a_keys = [k for k in ka if k not in kb_of]
            only_b_keys = [k for k in kb if k not in ka and k not in matched_b]
            only = ([] if part_b else [f"only in A ({len(only_a_keys)}): "
                                       f"{_fmt_list(show_key(k) for k in only_a_keys) or '-'}"]) + \
                   ([] if part_a else [f"only in B ({len(only_b_keys)}): "
                                       f"{_fmt_list(show_key(k) for k in only_b_keys) or '-'}"])
            if match:
                lines.append(f"Key {name}: {len(match)} more matched by their words (written differently on the two sides): "
                             + _fmt_list(f"{show_key(x)} ~ {show_key(y)}" for x, y in match.items()) + ".")
            both = list(kb_of)
            lines.append(f"Key {name}: {len(both)} in both" + (" among the rows shown" if part_a or part_b else "")
                         + "".join("; " + s for s in only) + ".")
            if version >= 3 and both:  # unpaired number columns that agree on the matched rows
                num_a = [i for i in only_a if _kind(a.iloc[:, i]) == "n"]
                num_b = [j for j in only_b if _kind(b.iloc[:, j]) == "n"]
                for i in num_a:
                    for j in num_b:
                        lab = _scaled_agreement([a.iat[ka[k], i] for k in both], [b.iat[kb[kb_of[k]], j] for k in both])
                        if lab is not None:
                            lines.append(f"Unpaired A.{a.columns[i]} and B.{b.columns[j]} agree on the shared keys "
                                         f"(B = A{lab}).")
                            num_b.remove(j)
                            break
            shown = (lambda x, y: " | ".join(_show_pair(x, y))) if version >= 3 else (lambda x, y: f"{_show(x)} | {_show(y)}")
            for i, j in pairs:
                if (i, j) in key:
                    continue
                d = [k for k in both if not _same(a.iat[ka[k], i], b.iat[kb[kb_of[k]], j])]
                if d:
                    lines.append(f"{a.columns[i]}: differs in {len(d)} of {len(both)} shared keys: "
                                 + _fmt_list(f"{show_key(k)} {shown(a.iat[ka[k], i], b.iat[kb[kb_of[k]], j])}" for k in d) + ".")
                elif both:
                    lines.append(f"{a.columns[i]}: same in all {len(both)} shared keys.")
        elif part_a and part_b:
            lines.append("No key column, and both sides show only some rows: values are not compared.")
        else:
            for i, j in pairs:
                oa, ob = _multiset_diff(a.iloc[:, i].tolist(), b.iloc[:, j].tolist())
                if part_a or part_b:  # list only what the complete side lacks
                    side, other, extra = ("A", "B", oa) if part_a else ("B", "A", ob)
                    lines.append(f"{a.columns[i]}: only in {side} ({len(extra)}): {_fmt_list(extra)}." if extra
                                 else f"{a.columns[i]}: every value {side} shows is in {other}.")
                elif not oa and not ob:
                    lines.append(f"{a.columns[i]}: same values (order ignored).")
                else:
                    lines.append(f"{a.columns[i]}: only in A ({len(oa)}): {_fmt_list(oa) or '-'}; "
                                 f"only in B ({len(ob)}): {_fmt_list(ob) or '-'}.")
    lines += _dup_columns(a, "A", part_a, version) + _dup_columns(b, "B", part_b, version)
    text = "\n".join(lines)
    return text if len(text) <= CAP else text[:CAP - 1] + "…"


if __name__ == "__main__":  # tiny self-check
    A = pd.DataFrame({"director": ["Mangold", "Russo A", "Russo J", "Elliott"], "movie_count": [2, 2, 2, 2]})
    B = pd.DataFrame({"director": ["Mangold", "Russo A", "Russo J", "Shahir"], "movie_count": [4, 3, 3, 3]})
    print(compare_results(A, B))
    print(compare_results(pd.DataFrame({"x": [4.82], "n": [18653]}), pd.DataFrame({"avg": [4.92]})))
