"""Pairwise judge prompt variants for rejudge_pools.py (Nov 2026 selection eval).

Every variant keeps the deployed placeholders ({question} {doc_section} {schema_section} {sql_a}
{res_a} {sql_b} {res_b}) and the deployed reply format (JSON with "winner"), so parsing and
P(A) reading are unchanged; only the instructions after the candidates differ. "base" is the
deployed prompt. The variants share one rules block, so rules - base isolates the rules and
diff_cmp / spec / diff_nocmp - rules isolate the procedure; diff_cmp - diff_nocmp isolates the
computed result comparison ({comparison}, from build_compare_cache.py). They come from the
design-half miss reading (documents/judge_prompt_eval.md) and name no database engine.
"""

from select_answer import PAIRWISE_PROMPT

_HEAD = """You are judging two candidate SQL answers to a database question.

Question: {question}
{doc_section}{schema_section}
--- Candidate A ---
SQL:
{sql_a}
Execution result:
{res_a}

--- Candidate B ---
SQL:
{sql_b}
Execution result:
{res_b}

"""
_REPLY = """

Reply with JSON only: {{"winner": "A" or "B", "reason": "<one sentence>"}}"""

assert PAIRWISE_PROMPT.startswith(_HEAD) and PAIRWISE_PROMPT.endswith(_REPLY)

RULES = """Rules:
- Both queries ran successfully on this database, and each execution result is the query's \
actual output. Dialect, portability, efficiency, style and how general the SQL is are not criteria.
- Columns: extra columns beyond what was asked are fine and are never a reason to prefer a \
candidate. A requested value that is missing or wrong is.
- Rows: the result must contain the rows the question asks for. Several items where the \
question asks for one, the wrong number of top items, or rows left out that belong (some \
years, groups or entities) make a result wrong.
- A difference between the two queries matters only if it changes the result on this \
database. A hard-coded value that the other result confirms, a guard for NULLs or zeros that \
never occur, an equivalent formula, or a tie-break that changes nothing is not a flaw.
- When the results differ, find the difference in the SQL that causes it and decide that \
difference against the question. Do not prefer numbers because they look more typical; this \
database may be small or unusual. Comments inside the SQL are claims, not evidence."""

ASK_RULES = """Which candidate correctly answers the question? The correct one returns the \
values the question asks for, at the granularity it asks for, computed the way the question \
and the reference documentation (when given) define them."""

COMPARISON = """--- Result comparison (computed from the two full results; it shows where they \
differ, not which one is right) ---
{comparison}

"""

_DIFF = """Which candidate correctly answers the question? Work in this order:
1. List the concrete differences between the two queries: joins, filters and time ranges, \
grain (one row per what), what is counted or summed (distinct items or rows), NULL and \
duplicate handling, ranking, ties and limits, units, signs and rounding, output columns.
2. For each difference, use {source} to say whether it changes the result on this database. \
Set aside every difference that changes no value.
3. Decide each remaining difference against the question and the reference documentation \
(when given).
4. Pick the candidate whose result-changing choices the question supports."""

ASK_SPEC = """Which candidate correctly answers the question? Work in this order:
1. Before weighing either candidate, write a short specification from the question and the \
reference documentation (when given) alone: the values to return; the grain (one row per \
what); which rows belong (filters, time range, whether items with zero or missing values \
count); how each value is computed (distinct items or rows, units, sign, any formula the \
documentation gives); ordering, limit and rounding. If the question allows two readings, \
write both.
2. Check each candidate's SQL and result against the specification item by item, using the \
values shown.
3. Pick the candidate that satisfies the specification on the items that change the result."""

VARIANTS = {
    "base": {"template": PAIRWISE_PROMPT},
    "rules": {"template": _HEAD + ASK_RULES + "\n\n" + RULES + _REPLY},
    "diff_cmp": {"template": _HEAD + COMPARISON + _DIFF.format(source="the result comparison")
                 + "\n\n" + RULES + _REPLY},
    "diff_nocmp": {"template": _HEAD + _DIFF.format(source="the two execution results")
                   + "\n\n" + RULES + _REPLY},
    "spec": {"template": _HEAD + ASK_SPEC + "\n\n" + RULES + _REPLY},
}
