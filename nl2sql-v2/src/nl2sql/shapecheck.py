"""Refuse a submission whose shape contradicts what the model itself said the
question asks for.

Nothing here derives from gold SQL or gold outputs: the expectation comes from
the model's own reading of the question, and the check is a self-consistency
test. That is the whole point — a contract built from the gold answer leaks the
answer's cardinality and, through its column names, often the aggregation to
apply, so it can measure a ceiling but can never ship.

The failure this targets is the largest single class in the trace analysis: the
model computes the right thing and hands back its working instead of the answer
(local202 returns the 5 qualifying states where the question asks how many;
local039 returns all 16 categories with the right one ranked first).

Advisory notes are heuristics over the question text and never block on their
own, because a false refusal costs steps and the step budget is already the
second-largest failure class.
"""

import re

import pandas as pd

# "which/what single thing" phrasings: the answer is one row.
_SINGULAR = re.compile(
    r"\b(which|what|who)\b[^.?]{0,80}\b(has|have|had|is|was|are)\b[^.?]{0,40}"
    r"\b(most|highest|largest|greatest|lowest|smallest|fewest|best|worst|top)\b"
    r"|\bhow many\b|\bwhat is the (total|overall|average|sum|number|percentage)\b",
    re.I)
# per-group phrasings: the answer is many rows.
_PLURAL = re.compile(r"\b(for each|per each|by each|each year|each month|list all|"
                     r"all the|breakdown|per \w+|grouped by)\b", re.I)
_PERCENT = re.compile(r"\bpercent|\bpercentage\b|\bpct\b", re.I)


def _declared_rows(expected_rows: str) -> int | None:
    """An exact row count if the model named one, else None for 'many'."""
    if expected_rows is None:
        return None
    s = str(expected_rows).strip().lower()
    if s.isdigit():
        return int(s)
    m = re.match(r"^(?:exactly\s+)?(\d+)\b", s)
    return int(m.group(1)) if m else None


def proportion_problem(question: str, df: pd.DataFrame) -> str | None:
    """Question says percentage, every value is a 0-1 proportion.

    Blocking, unlike the row heuristic: the trigger is narrow (the word has to
    appear AND the column has to stay under 1.0), and it is the local169 failure
    exactly — 0.9809 submitted where the gold wanted 98.09. A false refusal costs
    one step via confirm_shape.
    """
    if not _PERCENT.search(question or ""):
        return None
    for c in df.columns:
        v = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(v) and v.abs().max() <= 1.0 and (v.abs() > 0).any():
            return (f"the question says percentage but column {c!r} never exceeds 1.0 — "
                    f"that is a proportion; multiply by 100")
    return None


def advisory_notes(question: str, df: pd.DataFrame) -> list[str]:
    """Softer heuristics. Never block on their own — a false refusal costs steps,
    and running out of steps is itself the second-largest failure class."""
    notes = []
    if (len(df) > 1 and _SINGULAR.search(question or "")
            and not _PLURAL.search(question or "")):
        notes.append(f"the question reads as asking for one thing, but the result has "
                     f"{len(df)} rows — did you mean to aggregate or take the top one?")
    return notes


def check(question: str, df: pd.DataFrame, expected_rows: str,
          expected_columns: list | None) -> str | None:
    """None to accept, or the message explaining why the submission is refused."""
    problems, notes = [], advisory_notes(question, df)

    prop = proportion_problem(question, df)
    if prop:
        problems.append(prop)

    want_rows = _declared_rows(expected_rows)
    if want_rows is not None and want_rows != len(df):
        problems.append(f"you said the question asks for {want_rows} row(s); this result "
                        f"has {len(df)}")

    want_cols = [c for c in (expected_columns or []) if str(c).strip()]
    # Extra columns are harmless to the scorer, missing ones are fatal, so only
    # a result NARROWER than the model's own list is worth refusing.
    if want_cols and len(df.columns) < len(want_cols):
        problems.append(f"you listed {len(want_cols)} column(s) the question asks for "
                        f"({', '.join(map(str, want_cols))}); this result has only "
                        f"{len(df.columns)}: {', '.join(map(str, df.columns))}")

    if not problems:
        return None
    msg = ["SUBMISSION REFUSED — the result does not match the shape you stated:"]
    msg += [f"  - {p}" for p in problems]
    msg += [f"  note: {n}" for n in notes]
    msg.append("Fix the query and submit the corrected result, or call submit_result "
               "again with confirm_shape=true if the shape really is right.")
    return "\n".join(msg)
