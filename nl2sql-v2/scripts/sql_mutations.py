"""Near-miss variants of a gold query, one small change each, for judge training
negatives. Each operator models one error type from the selection failures:

  drop_distinct       DISTINCT removed (fan-out rows counted twice)
  count_star          COUNT(col) / COUNT(DISTINCT col) -> COUNT(*) (wrong denominator)
  row_number          RANK / DENSE_RANK -> ROW_NUMBER (ties at a cutoff dropped)
  inner_join          LEFT JOIN -> JOIN (groups with no match disappear)
  drop_null_guard     COALESCE(x, c) / NULLIF(x, c) -> x
  boundary            < <-> <=, > <-> >= against a constant
  like_widen          col = 'v' -> col LIKE '%v%' (overlapping categories)
  drop_condition      one AND-ed WHERE/HAVING condition removed
  flip_order          ASC <-> DESC where a LIMIT picks the top rows
  swap_column         a column replaced by another everywhere (e.g. id -> name)

A variant is a negative only if its result differs from the gold's on the data
(discriminating()); many are equivalent on a given database and must be dropped.
"""

import sqlglot
from sqlglot import exp


def _variants(tree, match, change):
    """One copy of the tree per node match() accepts, with change() applied to that
    node only. change returns the replacement (or the node, edited in place)."""
    out = []
    for i, node in enumerate(tree.walk()):
        if not match(node):
            continue
        t2 = tree.copy()
        n2 = next(n for j, n in enumerate(t2.walk()) if j == i)
        new = change(n2)
        if new is not n2:
            if n2 is t2:
                t2 = new  # the root has no parent to replace it in
            else:
                n2.replace(new)
        out.append(t2)
    return out


def _edit(node, **args):
    for k, v in args.items():
        node.set(k, v)
    return node


def _const(e) -> bool:
    return isinstance(e, (exp.Literal, exp.Cast, exp.Date, exp.Neg)) or (
        isinstance(e, exp.Anonymous) and e.name.upper() in ("DATE", "DATETIME"))


def _in_filter(node) -> bool:
    p = node.parent
    while p is not None and not isinstance(p, (exp.Where, exp.Having, exp.Select)):
        p = p.parent
    return isinstance(p, (exp.Where, exp.Having))


def _limited(node) -> bool:
    sel = node.find_ancestor(exp.Select)
    return sel is not None and sel.args.get("limit") is not None


OPERATORS = {
    "drop_distinct": [
        (lambda n: isinstance(n, exp.Select) and n.args.get("distinct"),
         lambda n: _edit(n, distinct=None)),
        (lambda n: isinstance(n, exp.Count) and isinstance(n.this, exp.Distinct)
         and len(n.this.expressions) == 1,
         lambda n: _edit(n, this=n.this.expressions[0])),
    ],
    "count_star": [
        (lambda n: isinstance(n, exp.Count) and isinstance(n.this, (exp.Column, exp.Distinct)),
         lambda n: _edit(n, this=exp.Star())),
    ],
    "row_number": [
        (lambda n: isinstance(n, exp.Window) and isinstance(n.this, (exp.Rank, exp.DenseRank)),
         lambda n: _edit(n, this=exp.RowNumber())),
    ],
    "inner_join": [
        (lambda n: isinstance(n, exp.Join) and str(n.args.get("side") or "").upper() == "LEFT",
         lambda n: _edit(n, side=None, kind=None)),
    ],
    "drop_null_guard": [
        (lambda n: isinstance(n, exp.Coalesce) and len(n.expressions) == 1
         and isinstance(n.expressions[0], exp.Literal), lambda n: n.this),
        (lambda n: isinstance(n, exp.Nullif) and isinstance(n.expression, exp.Literal),
         lambda n: n.this),
    ],
    "boundary": [
        (lambda n: isinstance(n, (exp.LT, exp.LTE, exp.GT, exp.GTE))
         and (_const(n.this) or _const(n.expression)),
         lambda n: {exp.LT: exp.LTE, exp.LTE: exp.LT, exp.GT: exp.GTE, exp.GTE: exp.GT}[
             type(n)](this=n.this, expression=n.expression)),
    ],
    "like_widen": [
        (lambda n: isinstance(n, exp.EQ) and isinstance(n.this, exp.Column)
         and isinstance(n.expression, exp.Literal) and n.expression.is_string and _in_filter(n),
         lambda n: exp.Like(this=n.this, expression=exp.Literal.string(f"%{n.expression.name}%"))),
    ],
    "drop_condition": [
        (lambda n: isinstance(n, exp.And) and _in_filter(n), lambda n: n.this),
        (lambda n: isinstance(n, exp.And) and _in_filter(n), lambda n: n.expression),
    ],
    "flip_order": [
        (lambda n: isinstance(n, exp.Ordered) and _limited(n),
         lambda n: _edit(n, desc=not n.args.get("desc"), nulls_first=None)),
    ],
}


def mutants(sql: str, dialect: str = "duckdb", swaps: dict | None = None,
            max_per_op: int = 4) -> list[tuple[str, str]]:
    """[(operator, sql)] for every single-change variant, without duplicates or the
    original. swaps: {column: replacement} for swap_column (e.g. an id and its name)."""
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    seen = {tree.sql(dialect=dialect)}
    out = []
    ops = dict(OPERATORS)
    for old, new in (swaps or {}).items():
        ops[f"swap_column:{old}->{new}"] = [(
            lambda n, old=old: isinstance(n, exp.Select) and any(
                c.name.lower() == old.lower() for c in n.find_all(exp.Column)),
            lambda n, old=old, new=new: n.transform(
                lambda c: exp.column(new, table=c.table or None)
                if isinstance(c, exp.Column) and c.name.lower() == old.lower() else c))]
    for name, rules in ops.items():
        n_op = 0
        for match, change in rules:
            for t2 in _variants(tree, match, change):
                s = t2.sql(dialect=dialect)
                if s not in seen and n_op < max_per_op:
                    seen.add(s)
                    out.append((name, s))
                    n_op += 1
    return out


def discriminating(variants, run, gold_df, ignore_order: bool = True) -> list[dict]:
    """The variants whose result the scorer rejects against the gold. run(sql) returns
    a DataFrame or raises; a variant that fails to run is not a usable negative."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from nl2sql.eval import _csv_roundtrip, compare_dataframes
    gold = _csv_roundtrip(gold_df.copy())
    out = []
    for op, sql in variants:
        try:
            df = run(sql)
        except Exception:
            continue
        if not compare_dataframes(_csv_roundtrip(df), gold, ignore_order=ignore_order):
            out.append({"operator": op, "sql": sql, "rows": int(df.shape[0])})
    return out
