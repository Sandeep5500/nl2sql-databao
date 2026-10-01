"""Rule-based sanity checks on a candidate answer (question + result only, no gold).

Deepika's proposal for the pass@K validator: before (or instead of) asking a model to
judge, flag candidates whose RESULT cannot be right for the question -- failed SQL, an
empty result, more rows than a "top N" allows, a list where one number is asked, ids
where names are asked, duplicate rows (wrong grain), an all-NULL column.

    flags = check_candidate(question, columns, rows, error)   # [] = passes
    keep  = prefilter(candidates)                              # unflagged, or all if none pass
"""

import csv
import io
import re

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "twenty": 20}
_PER_GROUP = re.compile(r"\b(each|per|for every|for all|by (?:each|every)|respectively|"
                        r"in every|within each|across)\b", re.I)
_TOP_N = re.compile(r"\b(?:top|first|highest|lowest|largest|smallest|best|worst|most|least)\s+"
                    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty)\b", re.I)
_SINGLE = re.compile(r"^\s*(how many|how much|what is the (?:total|average|number|count|sum|"
                     r"percentage|proportion|ratio|difference|median)|what was the (?:total|average|"
                     r"number|count|sum|percentage))\b", re.I)
_NAMES = re.compile(r"\b(names?|titles?)\b", re.I)


def parse_preview(preview: str) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(preview or "")))
    if not rows:
        return [], []
    return rows[0], [r for r in rows[1:] if r]


def check_candidate(question: str, columns: list[str], rows: list[list[str]],
                    n_rows: int | None = None, error: str | None = None) -> list[str]:
    """Reasons this result cannot answer the question; [] if none found.
    `rows` may be a preview; `n_rows` is the full row count when known."""
    if error:
        return ["sql_error"]
    n = len(rows) if n_rows is None else n_rows
    if n == 0:
        return ["empty_result"]
    flags = []
    grouped = bool(_PER_GROUP.search(question))
    m = _TOP_N.search(question)
    if m and not grouped:
        k = m.group(1).lower()
        k = int(k) if k.isdigit() else _NUM_WORDS[k]
        if n > k:
            flags.append(f"more_rows_than_top_{k}")
    if _SINGLE.search(question) and not grouped and n > 1:
        flags.append("list_where_one_value_asked")
    low = [c.lower() for c in columns]
    if _NAMES.search(question) and not any("name" in c or "title" in c for c in low) \
            and any(c == "id" or c.endswith("id") for c in low):
        flags.append("ids_where_names_asked")
    if rows and len(rows) > 1 and len({tuple(r) for r in rows}) < len(rows):
        flags.append("duplicate_rows")
    for j, c in enumerate(columns):
        vals = [r[j] for r in rows if j < len(r)]
        if vals and all(v.strip() in ("", "None", "nan", "NULL") for v in vals):
            flags.append(f"all_null_column:{c}")
            break
    return flags


def prefilter(candidates: list[dict], question: str) -> list[dict]:
    """Candidates that pass every check; all of them if none does (never empty)."""
    ok = [c for c in candidates if not c.get("flags")]
    return ok or candidates
