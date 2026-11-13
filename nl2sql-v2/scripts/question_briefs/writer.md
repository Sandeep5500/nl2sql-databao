# Question writer brief

You are writing questions for a dataset that will train an LLM judge to pick the correct SQL
answer among several candidate answers to analytics questions over SQLite databases (in the
style of Spider 2.0-Lite). Each item is a realistic, demanding business question with a
carefully verified gold SQL answer.

Your assignment message gives:
- your writer id W;
- your databases, with how many items of each kind to write for each;
- these paths:
  - WORK: your own directory. Write only here.
  - DS: the question set.
  - DOCS: BIRD's database folders.
  - PY: the Python to run.
  - REPO: the repository.

Write your items to WORK/items.jsonl, one JSON object per line.

## Item kinds

- **plain**: a hard multi-step analytics question with no designed trap.
- **lookalike_columns**: two columns could each seem to answer the question, but they hold
  different values, and the question's wording, read carefully, points to one of them.
  careless_sql uses the other one. Examples:
  - an order's order date, required date and shipped date;
  - the store where a sale happened (a sales column) vs the store a product belongs to (a
    product column);
  - a player's nationality vs birth country;
  - a list price vs the price paid after discount;
  - one column read with the wrong convention: cents vs dollars, a share stored 0-1 vs
    0-100, a season named by its start year.

  DS/traps/sites/<db>.json lists pairs found automatically. They are dates or years in one
  table that disagree, and same-named measures, dates or references on both sides of a join
  that disagree (a goalie's goals against and the team's). Not every pair makes a fair
  question; pick ones a careful analyst could tell apart from the wording. Look for others in
  the column documentation too: columns whose descriptions overlap.
- **grain**: the question asks for a result at one level or in one shape, and a hurried query
  answers at another. careless_sql answers at the wrong level or in the wrong shape. Examples:
  - average order value (each order's total, averaged) vs the average order line;
  - the average of per-customer averages vs one pooled average;
  - how many customers vs how many orders;
  - each category's share of its region's total vs of the grand total;
  - the top 3 within each group vs the top 3 overall;
  - one row per player vs one row per player-season;
  - one row with the answer vs one row per group.

  The scorer tolerates extra columns (see "How answers are scored"), so the careless
  result must differ some other way: a missing column, a different number of rows, or
  different values.
- **fanout**: joining a one-to-many table before summing or counting repeats rows.
- **Other trap kinds.** Use whichever the data offers:
  - tie_at_cutoff: ties at a top-k cutoff; the careless query uses LIMIT or ROW_NUMBER.
  - shared_name: one name for several IDs; the careless query groups by name.
  - null_or_zero: NULLs or zeros change an average, count or ratio.
  - overlapping: category values contain one another, or differ only in spaces or case.
  - mixed_dates: text dates in several formats.
  - orphan_rows: child rows whose key matches no parent row.

If a database has no honest case of an assigned kind, write a different trap kind instead,
and say so in your reply. A weak or contrived trap is worse than a substitution.

## Difficulty

The answers to these questions come from a capable SQL agent that runs each question four
times. A question it answers correctly all four times teaches the judge nothing. In the last
batch, that was two thirds of the questions: most needed one join and one aggregate, and
their single trap was easy to spot. Write questions the agent gets right only some of the
time:
- Chain three or more steps, each feeding the next. For example: a metric per entity, then
  compared with a benchmark computed at another level, then ranked within groups. Or: a
  first event per customer, then a cohort, then a rate per cohort.
- Compute numbers at two levels: per order, then averaged per customer; per player-season,
  then summed per team.
- In a trap item, the trap must sit on the path a natural query takes, not in a corner of
  it. Add a second pitfall of another kind where the data has an honest one (NULLs in a
  column you average; a name shared by two IDs in a table you group).
- Use the less obvious tables a database has: a link table, a history table, a second
  date column.

Hard must not mean vague. Every added step still has to be pinned down exactly (see "The
question"); a question two careful analysts could read differently is worse than an easy
one. Do not make a question harder by making it longer than it needs to be, by using rare
words, or by asking about something no analyst would want.

## Files and tools

Run everything from REPO/nl2sql-v2. The shell is zsh: start each command with `export REPO=... DS=...` (the paths from your assignment), or put the commands in a bash script, since zsh rejects some inline assignments.
- Databases (SQLite; the agent and the checker query them through DuckDB):
  DS/databases/<db>.sqlite
- Trap facts found in the data: DS/traps/sites/<db>.json
- Column documentation (written by people; read it before writing):
  DOCS/<db>/database_description/<table>.csv. It is sometimes wrong (fiscal years described
  as release years, timestamps described as durations): check what a question relies on
  against the data.
- Questions that already exist on your databases: WORK/existing_<db>.txt. Yours must ask
  about different things, not paraphrases of these.
- Exploring:

  ```
  $PY -c "import sys; sys.path.insert(0, 'src'); from nl2sql.db import Database; db = Database('$DS/databases/<db>.sqlite'); print(db.list_tables()); print(db.describe_table('<table>')); print(db.query('<any DuckDB SQL>', 30))"
  ```

- Checker. Every item must pass:

  ```
  NL2SQL_DATASET_DIR=$DS $PY scripts/validate_trap_items.py --items $WORK/items.jsonl --rounding-check --report $WORK/check.report.json
  ```

  It checks that:
  - the gold runs on DuckDB and returns 1-50 rows;
  - the gold is deterministic: the same result twice, and no LIMIT cutting through tied
    values;
  - no value sits exactly on a rounding boundary at the precision the gold rounds it to
    (1012.125 at 2 decimals, 6.25 at 1), where two correct solvers could round either way;
  - for a trap item, the careless query runs and the benchmark scorer rejects its result;
  - the question has 30-120 words.

  Fix and re-run until every item passes; if one cannot be made to pass, replace it with a
  new item of the same kind on the same database.

## How answers are scored

The benchmark scorer compares results column by column. Every column of the gold result
must equal some column of the answer, as a list of values: row order is ignored, and
numbers match within 0.01. Extra columns in an answer are ignored. You do not need to read
the scorer's code.

## Item format

```
{"id": "<W>_<db>_<n>", "db": "<db>", "kind": "<kind>", "gold_sql": "...", "careless_sql": "<empty string for plain>", "intent": "<one sentence saying exactly what gold_sql returns>", "question": "..."}
```

## The gold

- Usually use 2-6 tables (fewer when the database is one wide table), with CTEs or window
  functions where they are natural (about 150-450 tokens).
- Return 1-30 rows (the checker allows up to 50; stay at 30).
- Make it deterministic: order by enough columns to separate ties, and keep tied rows at a
  cutoff (RANK() <= k, not LIMIT k). "The top k, with ties" means every entry whose value
  equals the k-th entry's value (RANK, not DENSE_RANK); say so when it matters.
- If a table repeats detail rows that a natural query would count twice, state in the
  question how to count them ("each release once"), or keep the question away from them.
- Group by IDs, not names, wherever names can repeat; show the name as well.
- When the question counts every entity of a kind ("each organization", "every year with a
  revenue record"), start from that entity's table and LEFT JOIN the rest, with COALESCE to
  0, even if no entity lacks rows today. Golds are also run on altered copies of the
  database, and an inner join that silently drops an entity with no rows was the most
  common gold error in the first wave.
- Use ROUND(x, 2) for non-integers. If the rounding check rejects a value on a .xx5
  boundary, round to 3 decimals or change the filter.
- Round only final values, never a value computed from already-rounded ones, and give
  differences, gaps and changes 3 decimals. A correct answer that rounds at another step
  can otherwise miss the scorer's 0.01 tolerance (8.17 vs 8.16 fails).
- Output labels must be values from the data, or text the question spells out exactly
  (the scorer compares strings exactly): "label tech employers 'tech' and the others
  'other'". Do not output a text column whose stored values carry stray spaces or mixed
  case ("Far North " next to "Central"): a solver who tidies them misses, and one who does
  not is right only by accident. Return an ID or a clean column instead.
- When matching text, say how whenever it changes the answer: whole word or anywhere in the
  name ("Park" vs "Parkview"), ignoring capitalization or not, and whether spellings that
  differ only in case are the same entity.
- Check every gold a second way before moving on: write a differently built query, or use
  pandas on the SQLite file, and look at the rows it returns.

## The question

Write the kind of question an analyst asks in a business review, needing several steps of
logic. Some patterns:
- a metric per entity, then a rank, filter or comparison;
- change between stated periods;
- cohorts and first or last events;
- the top k within each group;
- running totals;
- conditional counts and ratios;
- comparison with an average or benchmark.

Use 40-120 words of plain business language. Use no SQL words, and no table or column names
unless they read as ordinary words. A careful analyst must be able to reach exactly your
result from the question alone. So pin down:
- the filters and time range;
- what is counted or summed, and per what: the level of every number;
- whether entities with no matching records are included (with 0) or left out;
- whether self-references count (a paper citing itself, an employee listed as their own
  manager), when the data has any;
- whether rows whose link points at nothing count. Check for these orphan rows in the
  tables you use; if any exist and they change the answer, the question must say how to
  treat them;
- how ties are treated: "include every tied entry", or a stated tie-break;
- rounding;
- the output columns, in order.

Do not explain how to compute the answer.

For a trap item:
- The trap fact must matter, and careless_sql must be what a capable but hurried analyst
  would write and get wrong because of it.
- Its result must look believable: no shares above 100%, no negative counts, nothing a
  glance would reject.
- It must be a complete answer in the asked shape apart from the trap: if the question asks
  for an ID, the careless query returns one too (for example MIN(id) when it groups by
  name).
- Do not hint at the trap. Stating a counting rule plainly is not a hint; it is required
  precision ("include customers with no orders, with 0"; "count every sale on record, even
  when its product is no longer listed"). A hint warns about the pitfall or explains it
  ("note that some products appear twice"; "be careful to count each order once").
- For lookalike_columns, the wording that settles which column is meant must be ordinary
  business language ("the date each order shipped", "the store where the purchase was
  made"), not a column name and not a warning. For grain, state the level and shape just as
  plainly ("for each customer", "a single figure", "one row per region").

Before finishing, reread each question as a stranger who has only the question and the
database. If a second reasonable reading gives a different result, reword the question.

Example (on a database you do not have; for format and style only):

```
{"id": "w0_financial_1", "db": "financial", "kind": "fanout", "gold_sql": "WITH d AS (SELECT DISTINCT district_id FROM account WHERE frequency = 'POPLATEK MESICNE') SELECT di.A3 AS region, SUM(CAST(di.A4 AS BIGINT)) AS population FROM district di JOIN d ON d.district_id = di.district_id GROUP BY di.A3 ORDER BY population DESC, region", "careless_sql": "SELECT di.A3 AS region, SUM(CAST(di.A4 AS BIGINT)) AS population FROM district di JOIN account a ON a.district_id = di.district_id WHERE a.frequency = 'POPLATEK MESICNE' GROUP BY di.A3 ORDER BY population DESC", "intent": "Per region, total population of the districts that have at least one account with monthly statements, each district counted once, largest first.", "question": "For each region, what is the combined population of the districts that have at least one account receiving monthly statements? Return the region and its population, from the most populous region to the least populous."}
```

## DuckDB notes

- `/` on integers gives a decimal; `//` is integer division.
- Write AS before every column alias (`SUM(x) AS share`, not `SUM(x) share`): without AS,
  common words such as year, rows, share and value fail to parse.
- Double-quote names that are SQL keywords: "order", "group", "end", "window", "desc",
  "limit", "offset".
- CAST(text AS DATE) only accepts YYYY-MM-DD text. For other formats, use
  STRPTIME(col, '%m/%d/%Y') (or TRY_STRPTIME). Check a column's date format before using it.
- LIKE is case-sensitive; ILIKE is not.
- A few columns hold values DuckDB cannot read as their declared type (a date such as
  '1960-0-0'), and any query touching them fails. Avoid them, or read them with TRY_CAST.
- Some tables have columns declared INTEGER that hold text. The tools then read every column
  as text: use TRY_CAST(col AS DOUBLE) for math on those tables.

## Rules

- Do not open anything under REPO/Spider2 or REPO/spider2-dce, and do not use Spider 2.0
  questions or data in any way: it is the test set.
- Open only the databases, the trap facts, the column documentation and your WORK directory.
  In particular, do not open DS/gold, DS/questions.jsonl or other writers' directories. You
  may read the code under REPO/nl2sql-v2 (the checker and scorer), though this brief should
  make that unnecessary.
- Write only to WORK. Temporary files go under WORK/tmp.
- Work on your own. Do not start other agents: your questions are checked later by solvers
  who have not seen your work, and a solver you start yourself is not independent.
- When done, reply with:
  - the number of items that pass;
  - the kinds per database, and any substitutions;
  - any item you had doubts about;
  - anything about these instructions that made the task harder than it should be.
