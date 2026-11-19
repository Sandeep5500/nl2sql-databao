"""Pairwise judge prompt variants for rejudge_pools.py (Nov 2026 selection eval).

Every variant keeps the deployed placeholders ({question} {doc_section} {schema_section} {sql_a}
{res_a} {sql_b} {res_b}) and the deployed reply format (JSON with "winner"), so parsing and
P(A) reading are unchanged; only the instructions after the candidates differ, except dc_rf (results
before SQL), dc_full (BigQuery doc and schema uncut, via "context") and dc_facts (BigQuery dataset notes,
via "context"). LISTWISE is the round-3 prompt for listwise_pools.py. "base" is the old deployed
prompt; diff_cmp is deployed since Nov 13. The variants share one rules block, so rules - base isolates the rules and
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

# From the BigQuery miss reading (judge_results.md §11, Nov 18): a filter the question does not ask for
# taken as a refinement, and reasons about how a query is written held against a right result.
SCOPE_RULE = """
- Filters: each filter, exclusion or list of allowed values must come from the question or the \
reference documentation. One that neither of them states or implies (a typed-in list of names or codes, a \
code the query's author picked, dropping rows that look unusual) is a flaw when it changes the \
result. Rows belong if the data files them under what the question asks about, even when they look \
out of place; a filter the question does imply (a place, period or category it names) is required."""

LIT_STEP = """
5. Before answering, check each reason you hold against a candidate: if it is about how the query \
is written (hard-coded values, typed-in lists, literal dates or IDs, generality, robustness, style) \
and does not change a value or row in the results, drop it."""

_DIFF_CMP = _DIFF.format(source="the result comparison")

# Round 2 (Nov 18, documents/bq_judge_improvement_plan.md): how the judge works through a pair, not what
# it is told to reject. dc_spec writes the specification of ASK_SPEC before diff_cmp's steps; dc_rf shows
# both results and the comparison before the SQL; dc_brief asks the 27B for shorter reasoning (its calls
# without a verdict reach the 8192-token limit).
_SPEC_DIFF = """Which candidate correctly answers the question? Work in this order:
1. Before weighing either candidate, write a short specification from the question and the \
reference documentation (when given) alone: the values to return; the grain (one row per \
what); which rows belong (the filters and time range the question states or implies, and whether \
items with zero or missing values count); how each value is computed (distinct items or rows, \
units, sign, any formula the documentation gives); ordering, limit and rounding. If the question \
allows two readings, write both.
2. List the concrete differences between the two queries: joins, filters and time ranges, \
grain (one row per what), what is counted or summed (distinct items or rows), NULL and \
duplicate handling, ranking, ties and limits, units, signs and rounding, output columns.
3. For each difference, use the result comparison to say whether it changes the result on this \
database. Set aside every difference that changes no value.
4. Decide each remaining difference against your specification.
5. Pick the candidate whose result-changing choices the specification supports."""

_HEAD_RF = """You are judging two candidate SQL answers to a database question.

Question: {question}
{doc_section}{schema_section}
--- Candidate A: execution result ---
{res_a}

--- Candidate B: execution result ---
{res_b}

""" + COMPARISON + """--- Candidate A: SQL ---
{sql_a}

--- Candidate B: SQL ---
{sql_b}

"""

_RF = """Which candidate correctly answers the question? Work in this order:
1. Start from the two results and the comparison: say what the question asks for and where the \
two results disagree (rows present or missing, values, grain, columns).
2. For each disagreement, use the SQL only to find what causes it: the join, filter, time range, \
grouping, counting or formula behind it.
3. Decide each disagreement against the question and the reference documentation (when given). \
How a query is written is not a disagreement unless it changes a value or row.
4. Pick the candidate whose result answers the question."""

BRIEF = """
Keep your reasoning short: go through the steps once, a line or two per point, do not re-check \
points already settled, and answer as soon as the decision is clear."""

VARIANTS = {
    "base": {"template": PAIRWISE_PROMPT},
    "rules": {"template": _HEAD + ASK_RULES + "\n\n" + RULES + _REPLY},
    "diff_cmp": {"template": _HEAD + COMPARISON + _DIFF_CMP + "\n\n" + RULES + _REPLY},
    "diff_nocmp": {"template": _HEAD + _DIFF.format(source="the two execution results")
                   + "\n\n" + RULES + _REPLY},
    "spec": {"template": _HEAD + ASK_SPEC + "\n\n" + RULES + _REPLY},
    # diff_cmp plus one change each, then both (BigQuery ablation, Nov 18)
    "dc_scope": {"template": _HEAD + COMPARISON + _DIFF_CMP + "\n\n" + RULES + SCOPE_RULE + _REPLY},
    "dc_lit": {"template": _HEAD + COMPARISON + _DIFF_CMP + LIT_STEP + "\n\n" + RULES + _REPLY},
    "dc_v2": {"template": _HEAD + COMPARISON + _DIFF_CMP + LIT_STEP + "\n\n" + RULES + SCOPE_RULE + _REPLY},
    # round 2 (Nov 18)
    "dc_spec": {"template": _HEAD + COMPARISON + _SPEC_DIFF + "\n\n" + RULES + _REPLY},
    "dc_rf": {"template": _HEAD_RF + _RF + "\n\n" + RULES + _REPLY},
    "dc_brief": {"template": _HEAD + COMPARISON + _DIFF_CMP + "\n\n" + RULES + BRIEF + _REPLY},
    # diff_cmp with BigQuery's doc and schema uncut (rejudge_pools.Contexts): the deployed cuts (8000 / 40000
    # chars) hide the GA360 field definitions (doc 35,736 chars) and the end of wide tables (up to 56,963)
    "dc_full": {"template": _HEAD + COMPARISON + _DIFF_CMP + "\n\n" + RULES + _REPLY,
                "context": {"doc_chars": 40000, "schema_chars": 60000}},
    # round 3 (Nov 18): diff_cmp plus short notes from each BigQuery dataset's official documentation (grain,
    # identifying columns, special codes and flags, units, time precision; rejudge_pools.py --facts). Spider2
    # prompts are unchanged.
    "dc_facts": {"template": _HEAD + COMPARISON + _DIFF_CMP + "\n\n" + RULES + _REPLY, "context": {"facts": True}},
}

# Round 3 listwise judge (listwise_pools.py): every distinct result of a question in one call, for questions
# with three or four of them, where the three wrong results often share one mistake and a round-robin makes
# the right one beat each of them in turn. diff_cmp's steps and rules, worded for several candidates; the
# candidates are numbered so that A and B can keep their meaning inside each pairwise comparison.
_LW_HEAD = """You are judging {n} candidate SQL answers to a database question.

Question: {question}
{doc_section}{schema_section}
{candidates}
--- Result comparisons (computed from the full results; they show where results differ, not which one \
is right; in each comparison, A and B stand for the two candidates named in its heading) ---
{comparisons}

"""

_LW_STEPS = """Which candidate correctly answers the question? Work in this order:
1. List the points on which the candidates' queries differ: joins, filters and time ranges, grain (one \
row per what), what is counted or summed (distinct items or rows), NULL and duplicate handling, ranking, \
ties and limits, units, signs and rounding, output columns. Note which candidates take each side.
2. For each point, use the result comparisons to say whether it changes the result on this database. \
Set aside every point that changes no value.
3. Decide each remaining point against the question and the reference documentation (when given). How \
many candidates take a side is not evidence for it.
4. Pick the candidate whose result-changing choices the question supports."""

LW_RULES = """Rules:
- Every query ran successfully on this database, and each execution result is the query's actual \
output. Dialect, portability, efficiency, style and how general the SQL is are not criteria.
- Columns: extra columns beyond what was asked are fine and are never a reason to prefer a \
candidate. A requested value that is missing or wrong is.
- Rows: the result must contain the rows the question asks for. Several items where the \
question asks for one, the wrong number of top items, or rows left out that belong (some \
years, groups or entities) make a result wrong.
- A difference between queries matters only if it changes the result on this database. A \
hard-coded value that another result confirms, a guard for NULLs or zeros that never occur, an \
equivalent formula, or a tie-break that changes nothing is not a flaw.
- When results differ, find the difference in the SQL that causes it and decide that difference \
against the question. Do not prefer numbers because they look more typical; this database may be \
small or unusual. Comments inside the SQL are claims, not evidence."""

LISTWISE = _LW_HEAD + _LW_STEPS + "\n\n" + LW_RULES + """

Reply with JSON only: {{"winner": <the number of the correct candidate>, "reason": "<one sentence>"}}"""

